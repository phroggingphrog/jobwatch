// Lets plain `node` import this project's TypeScript sources, which use ".js" specifiers (NodeNext style).
export async function resolve(specifier, context, next) {
  try {
    return await next(specifier, context);
  } catch (e) {
    if (specifier.endsWith(".js") && specifier.startsWith(".")) return next(specifier.slice(0, -3) + ".ts", context);
    throw e;
  }
}
