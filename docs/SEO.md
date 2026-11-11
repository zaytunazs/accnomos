# SEO

Indexed: the nine public pages in `sitemap.xml` (`/`, `/how-it-works`, `/help`, `/try`, `/join`, `/privacy`, `/terms`, `/models`, `/ai-models`), each with its own canonical URL.
Not indexed: every app shell (`/review`, `/bank`, `/settings` and the rest listed in `robots.ts`) is `Disallow`ed in `robots.txt` and carries `noindex, nofollow`; signed out they only ever show sample pages.
Structured data: the landing page carries one JSON-LD block (`Organization` + `SoftwareApplication`, no ratings or offers claimed).
