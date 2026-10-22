suppressPackageStartupMessages({library(rjags); library(coda); library(jsonlite)})
args <- commandArgs(trailingOnly=TRUE)
input <- fromJSON(args[1], simplifyVector=FALSE)
out <- args[2]
model_path <- args[3]
iter <- as.integer(args[4])
stopifnot(iter >= 1000, iter <= 100000)
sets <- input$sets
n <- length(sets); K <- length(input$names); F <- length(input$families)
X <- array(0, c(n,3,K)); family <- matrix(0L,n,3); y <- integer(n); holdout <- logical(n)
for(s in seq_len(n)) {
  holdout[s] <- sets[[s]]$holdout
  y[s] <- sets[[s]]$y
  for(a in 1:3) {
    X[s,a,] <- unlist(sets[[s]]$x[[a]])
    family[s,a] <- sets[[s]]$family[[a]]
  }
}
train <- which(!holdout); test <- which(holdout)
stopifnot(length(train)>=20, length(test)>=5)
prior_mean <- unlist(input$prior_means); a0 <- rep(0, F)
seeds <- c(1103L,2207L,3301L,4409L)
set.seed(20261011)
model <- jags.model(model_path, data=list(N=length(train),K=K,F=F,
  X=X[train,,,drop=FALSE],family=family[train,,drop=FALSE],y=y[train],prior_mean=prior_mean,a0=a0),
  n.chains=4,n.adapt=1500,quiet=TRUE,
  inits=lapply(seeds,function(seed) list(.RNG.name='base::Mersenne-Twister',.RNG.seed=seed)))
update(model,2500,progress.bar='none')
samples <- coda.samples(model,c('beta','alpha','alpha_raw','mu_alpha','tau'),n.iter=iter,progress.bar='none')
draws <- do.call(rbind,lapply(samples,as.matrix))
rhat <- tryCatch(gelman.diag(samples,multivariate=FALSE,autoburnin=FALSE)$psrf[,1],error=function(e) setNames(rep(NA_real_,ncol(draws)),colnames(draws)))
ess <- effectiveSize(samples)
summary_one <- function(v) {
 h <- HPDinterval(as.mcmc(v),prob=.95)
 d <- density(v)
 list(mode=unname(d$x[which.max(d$y)]),mean=mean(v),sd=sd(v),hdi_low=h[1,1],hdi_high=h[1,2])
}
parameters <- setNames(lapply(colnames(draws),function(name) {
 v <- draws[,name]; e <- unname(ess[name]); sdv <- sd(v)
 c(summary_one(v),list(rhat=unname(rhat[name]),ess=e,mcse=sdv/sqrt(e),mcse_ratio=1/sqrt(e)))
}),colnames(draws))
get_beta <- function(d) d[,sprintf('beta[%d]',seq_len(K)),drop=FALSE]
get_alpha <- function(d) d[,sprintf('alpha[%d]',seq_len(F)),drop=FALSE]
log_score <- function(beta,alpha) {
 scores <- vapply(test,function(s) {
  u <- matrix(0,nrow(beta),4)
  for(a in 1:3) u[,a] <- alpha[,family[s,a]] + as.vector(beta %*% X[s,a,])
  e <- exp(u-apply(u,1,max)); p <- e[,y[s]]/rowSums(e)
  log(max(mean(p),.Machine$double.xmin))
 },numeric(1))
 list(total=sum(scores),per_set=unname(scores))
}
# Actual prior predictive integration, not plug-in prior-mean utility.
set.seed(20261012)
prior_n <- 20000
pb <- matrix(rnorm(prior_n*K,rep(prior_mean,each=prior_n),.5),prior_n,K)
pm <- rnorm(prior_n); pt <- abs(rnorm(prior_n,0,.5))
pa <- matrix(0,prior_n,F)
for(f in seq_len(F)) pa[,f] <- pm+a0[f]+pt*rnorm(prior_n)
posterior_score <- log_score(get_beta(draws),get_alpha(draws))
prior_score <- log_score(pb,pa)
# Retain a deterministic, evenly spaced subset for posterior prediction.
keep <- unique(round(seq(1,nrow(draws),length.out=min(4000,nrow(draws)))))
result <- list(n_train=length(train),n_holdout=length(test),chains=4,seeds=as.list(seeds),
 iterations=iter,parameters=parameters,holdout_log_score=posterior_score$total,
 prior_log_score=prior_score$total,holdout_per_set=posterior_score$per_set,
 prior_per_set=prior_score$per_set,draws=list(beta=unname(get_beta(draws)[keep,,drop=FALSE]),
 alpha=unname(get_alpha(draws)[keep,,drop=FALSE])))
write_json(result,out,auto_unbox=TRUE,digits=16,pretty=TRUE,na='null')
# Trace/density are local audit artifacts; no candidate text is included.
pdf(paste0(out,'.trace.pdf')); plot(window(samples,thin=max(1L,as.integer(iter/2000L)))); dev.off()
