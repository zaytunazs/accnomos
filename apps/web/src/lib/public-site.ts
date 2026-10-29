/**
 * The public website: which routes get the marketing shell (top menu, footer, the "Ask about Accnomos" chat) while
 * this device is not signed in, and the small shared pieces of it. Signed in, the same routes use the app shell.
 */

/**
 * Routes shown in the marketing shell to signed-out visitors. `/` is the landing page (signed in: Home); `/judges`
 * is the demo guide (inside a demo sandbox, which counts as signed in, it keeps the app shell and the demo bar);
 * `/meta-models` says which Meta model does which job.
 */
export const PUBLIC_PATHS = new Set(["/", "/how-it-works", "/meta-models", "/privacy", "/terms", "/judges", "/join"]);

export const isPublicPath = (path: string) => PUBLIC_PATHS.has(path);

/**
 * The build the hackathon judges see (NEXT_PUBLIC_SUBMISSION_MODE, default "1"): "Try the demo" and "Sign in with
 * Microsoft", no launch date and no "coming soon". "0" is the pre-launch site for public traffic: "Launching
 * November 2026 — get notified" by e-mail, the demo, and sign-in tucked away as "Early access / testers".
 * e2e/submission-mode.spec.ts checks the default build has none of the pre-launch words.
 */
export const SUBMISSION_MODE = process.env.NEXT_PUBLIC_SUBMISSION_MODE !== "0";

/**
 * Whether pre-launch copy may be in this build at all: the pre-launch build, or a test build (whose specs flip the mode
 * per page, lib/submission-mode.ts). For server components; client components write the env test out in place so
 * the bundler folds it (components/Prelaunch.tsx).
 */
export const PRELAUNCH_IN_BUILD =
  process.env.NEXT_PUBLIC_SUBMISSION_MODE === "0" || process.env.NEXT_PUBLIC_TEST_MODE === "1";

export const LAUNCH = "November 2026";

/** Where the chat and the footer send anything the site cannot answer (runtime: PUBLIC_CONTACT_EMAIL). */
export const CONTACT_EMAIL = process.env.NEXT_PUBLIC_CONTACT_EMAIL || "admin@zaytunauk.co.uk";

/** "Try the demo": the judges' sandbox guide (src/app/judges); DemoLink.tsx starts the sandbox on the way there. */
export const DEMO_GUIDE = "/judges";

/** What is not tested against real services, kept in the public repository (docs/HONESTY.md). */
export const HONESTY_URL = "https://github.com/zaytunazs/accnomos/blob/main/docs/HONESTY.md";

/** Fired by the menu's "Ask about Accnomos" button; the chat widget opens on it. */
/** Pre-launch "get notified": no database, so an e-mail to the team. Empty in a submission build (folded away). */
export const NOTIFY_HREF =
  process.env.NEXT_PUBLIC_SUBMISSION_MODE === "0"
    ? `mailto:${CONTACT_EMAIL}?subject=${encodeURIComponent("Notify me at launch")}&body=${encodeURIComponent(
        "Hello, please let me know when Accnomos launches.\n\nName:\nBusiness:\n",
      )}`
    : "";

export const OPEN_CHAT_EVENT = "accnomos:open-chat";

export function openChat(question?: string): void {
  window.dispatchEvent(new CustomEvent(OPEN_CHAT_EVENT, { detail: { question } }));
}

/**
 * Runs before first paint (layout.tsx): marks <html data-signed-in> when this device holds a Microsoft sign-in, the
 * same test as lib/signed-in.ts, so a signed-in owner opening `/` never sees the landing page flash before Home.
 */
export const SIGNED_IN_PROBE = `try{var L=localStorage,l=null,e=0,s=0;for(var i=0;i<L.length;i++){var k=L.key(i)||"";if(k.indexOf("msal.accnomos-")===0){s=1;break}if(/^msal\\.(\\d+\\.)?account\\.keys$/.test(k)){try{var v=JSON.parse(L.getItem(k)||"[]");l=l||(Array.isArray(v)&&v.length>0)}catch(x){l=true}}else if(/^msal\\.\\d+\\|/.test(k))e=1}if(!s)s=l===null?e:l;if(s)document.documentElement.setAttribute("data-signed-in","")}catch(x){}`;
