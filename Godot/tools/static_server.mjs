import http from "node:http";
import { createReadStream, existsSync, statSync } from "node:fs";
import { extname, isAbsolute, join, relative, resolve } from "node:path";

const root = resolve(process.argv[2] ?? "build/web");
const port = Number(process.argv[3] ?? 8768);
const host = process.argv[4] ?? "127.0.0.1";
const projectRoot = process.argv[5] ? resolve(process.argv[5]) : undefined;
const dynamicSessionsRoot = process.argv[6]
  ? resolve(process.argv[6])
  : undefined;

const mime = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".wasm": "application/wasm",
  ".pck": "application/octet-stream",
  ".json": "application/json; charset=utf-8",
  ".ogv": "video/ogg",
  ".png": "image/png",
};

function containedPath(base, pathname) {
  const candidate = resolve(join(base, pathname.replace(/^[/\\]+/, "")));
  const relativePath = relative(base, candidate);
  if (
    relativePath === ".." ||
    relativePath.startsWith(`..\\`) ||
    relativePath.startsWith("../") ||
    isAbsolute(relativePath)
  ) {
    return undefined;
  }
  return candidate;
}

function resolveRequestPath(pathname) {
  const processedPrefix = "/assets/processed_sessions/";
  if (dynamicSessionsRoot && pathname.startsWith(processedPrefix)) {
    const dynamicPath = containedPath(
      dynamicSessionsRoot,
      pathname.slice(processedPrefix.length),
    );
    if (dynamicPath && existsSync(dynamicPath)) {
      return dynamicPath;
    }
  }
  if (projectRoot && pathname.startsWith("/assets/")) {
    return containedPath(projectRoot, pathname);
  }
  if (pathname === "/favicon.ico") {
    return containedPath(root, "/index.png");
  }
  return containedPath(root, pathname);
}

const server = http.createServer((request, response) => {
  if (!["GET", "HEAD"].includes(request.method ?? "")) {
    response.writeHead(405, {
      Allow: "GET, HEAD",
      "Cache-Control": "no-store",
    });
    response.end("Method not allowed");
    return;
  }

  let pathname;
  try {
    const url = new URL(request.url ?? "/", `http://${host}:${port}`);
    pathname =
      url.pathname === "/" ? "/index.html" : decodeURIComponent(url.pathname);
  } catch {
    response.writeHead(400);
    response.end("Bad request");
    return;
  }

  const filePath = resolveRequestPath(pathname);
  if (!filePath) {
    console.log(`${request.method} ${pathname} -> 403`);
    response.writeHead(403, { "Cache-Control": "no-store" });
    response.end("Forbidden");
    return;
  }

  try {
    const stats = statSync(filePath);
    if (!stats.isFile()) {
      throw new Error("Not a regular file");
    }
    console.log(`${request.method} ${pathname} -> 200 ${stats.size}`);
    response.writeHead(200, {
      "Content-Type": mime[extname(filePath)] ?? "application/octet-stream",
      "Content-Length": stats.size,
      "Cache-Control": "no-store",
      "Access-Control-Allow-Origin": "*",
      "Cross-Origin-Opener-Policy": "same-origin",
      "Cross-Origin-Embedder-Policy": "require-corp",
    });
    if (request.method === "HEAD") {
      response.end();
      return;
    }
    const stream = createReadStream(filePath);
    stream.on("error", (error) => {
      console.error(`GET ${pathname} -> stream error: ${error.message}`);
      response.destroy(error);
    });
    stream.pipe(response);
  } catch {
    console.log(`${request.method} ${pathname} -> 404`);
    response.writeHead(404, { "Cache-Control": "no-store" });
    response.end("Not found");
  }
});

server.listen(port, host, () => {
  console.log(`Serving ${root} at http://${host}:${port}/`);
  if (projectRoot) {
    console.log(`Project assets: ${projectRoot}`);
  }
  if (dynamicSessionsRoot) {
    console.log(`Dynamic sessions: ${dynamicSessionsRoot}`);
  }
});
