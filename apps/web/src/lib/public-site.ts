/**
 * The public website: which routes get the marketing shell (top menu, footer, the "Ask about Accnomos" chat) while
 * this device is not signed in, and the small shared pieces of it. Signed in, the same routes use the app shell.
 */

/** Routes shown in the marketing shell to signed-out visitors. `/` is the landing page (signed in: Home). */
export const PUBLIC_PATHS = new Set(["/", "/how-it-works", "/privacy"]);

export const isPublicPath = (path: string) => PUBLIC_PATHS.has(path);

/** Where the chat and the footer send anything the site cannot answer (runtime: PUBLIC_CONTACT_EMAIL). */
export const CONTACT_EMAIL = process.env.NEXT_PUBLIC_CONTACT_EMAIL || "admin@zaytunauk.co.uk";

/** Fired by the menu's "Ask about Accnomos" button; the chat widget opens on it. */
export const OPEN_CHAT_EVENT = "accnomos:open-chat";

export function openChat(question?: string): void {
  window.dispatchEvent(new CustomEvent(OPEN_CHAT_EVENT, { detail: { question } }));
}

/**
 * Runs before first paint (layout.tsx): marks <html data-signed-in> when this device holds a Microsoft sign-in, the
 * same test as lib/signed-in.ts, so a signed-in owner opening `/` never sees the landing page flash before Home.
 */
export const SIGNED_IN_PROBE = `try{var s=0,L=localStorage;for(var i=0;i<L.length;i++){var k=L.key(i)||"";if(k.indexOf("msal.")!==0||k==="msal.version")continue;if(k==="msal.account.keys"||k.indexOf("msal.token.keys")===0){try{var l=JSON.parse(L.getItem(k)||"[]");if(!Array.isArray(l)||l.length){s=1;break}}catch(e){s=1;break}continue}s=1;break}if(s)document.documentElement.setAttribute("data-signed-in","")}catch(e){}`;
