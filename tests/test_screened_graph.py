"""The screened graph: a gate pass stops at SHORTLISTED and nothing reaches drafting."""
import asyncio

from jobwatch.util.llm import LLM
from pipeline import graph, screened, store
from pipeline.schemas import Stage
from test_pipeline import Gateway, confirmed_candidate, stage, world  # noqa: F401


def run_screened(world, gw):
    conn, add, run, drafts = world
    s = graph.Settings(concurrency=2)
    g = screened.ScreenedGraph(conn=conn, db_path=str(run.config.db_path), config=run.config, settings=s,
                               llm=LLM(transport=gw, keys=["test-key"]))
    return asyncio.run(g.run())


def test_gate_pass_goes_to_shortlisted_and_never_to_drafting(world):
    conn, add, run, drafts = world
    pid = add("Accounts Assistant")
    run_screened(world, Gateway())
    assert stage(conn, pid) == "shortlisted"
    nodes = [r["node"] for r in conn.execute("SELECT node FROM pipeline_events WHERE posting_id=? ORDER BY id", (pid,))]
    assert nodes == ["ingest", "extract", "evaluate", "gate"]
    assert conn.execute("SELECT COUNT(*) FROM pipeline_events WHERE to_stage IN (?,?)",
                        (str(Stage.DRAFT_QUEUED), str(Stage.DRAFTED))).fetchone()[0] == 0
    assert drafts["n"] == 0


def test_screened_edges_have_no_drafting_stages():
    assert Stage.DRAFT_QUEUED not in screened.SCREENED_EDGES and Stage.DRAFTED not in screened.SCREENED_EDGES
    assert Stage.SHORTLISTED in screened.TERMINAL
    assert graph.EDGES[Stage.SCORED].to == {Stage.DRAFT_QUEUED, Stage.ARCHIVED}      # the old graph is untouched
