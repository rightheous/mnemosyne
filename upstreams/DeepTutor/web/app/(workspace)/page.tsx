import { redirect } from "next/navigation";

/**
 * The workspace root opens the personal study library.
 * `next.config.js` may redirect `/` before routing, so this page is a fallback
 * for deployments that reach the App Router directly.
 */
export default function WorkspaceRootPage() {
  redirect("/learning/reading");
}
