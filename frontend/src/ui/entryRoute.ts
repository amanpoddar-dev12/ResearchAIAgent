/** UI entry choice only; access control remains on the server. */
export function entryPage(pathname: string, signedIn: boolean): "landing" | "research" {
  const path = pathname.replace(/\/$/, "") || "/";
  return !signedIn && (path === "/" || path === "/landing") ? "landing" : "research";
}
