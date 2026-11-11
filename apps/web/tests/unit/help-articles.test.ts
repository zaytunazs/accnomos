/**
 * The help centre's articles (src/content/help/articles.json): ids are stable slugs and unique, every related id and
 * every picture exists, and no article names an AI vendor or model, or uses pre-launch wording.
 */
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { test } from "node:test";
import { PRELAUNCH_WORDS, THIRD_PARTY_NAMES } from "../../scripts/prelaunch-words.mjs";

interface Article {
  id: string;
  title: string;
  category: string;
  steps: { title: string; body: string; image?: string; alt?: string }[];
  troubleshooting: { problem: string; fix: string }[];
  related: string[];
}
const data = JSON.parse(readFileSync(new URL("../../src/content/help/articles.json", import.meta.url), "utf8")) as {
  categories: { id: string }[];
  articles: Article[];
};
const ids = data.articles.map((a) => a.id);

test("article ids are unique slugs, in a known category, with steps", () => {
  assert.equal(new Set(ids).size, ids.length);
  const cats = new Set(data.categories.map((c) => c.id));
  for (const a of data.articles) {
    assert.match(a.id, /^[a-z0-9]+(?:-[a-z0-9]+)*$/);
    assert.ok(cats.has(a.category), a.id);
    assert.ok(a.steps.length >= 2, a.id);
    for (const r of a.related) assert.ok(ids.includes(r), `${a.id} -> ${r}`);
  }
});

test("every picture an article uses is in public/help, with alt text", () => {
  for (const a of data.articles)
    for (const s of a.steps)
      if (s.image) {
        assert.match(s.image, /^\/help\/[a-z0-9-]+\.webp$/);
        assert.ok(existsSync(new URL(`../../public${s.image}`, import.meta.url)), `${a.id}: ${s.image} is missing`);
        assert.ok(s.alt && s.alt.length > 10, `${a.id}: ${s.image} has no alt text`);
      }
});

test("no AI vendor or model names, and no pre-launch words", () => {
  const text = JSON.stringify(data);
  for (const re of [...PRELAUNCH_WORDS, /\bsoon\b/i, /\bmeta\b/i, /\bmuse\b/i, /glimmer/i, /\bSAM\b/, ...THIRD_PARTY_NAMES])
    assert.ok(!re.test(text), `articles.json matches ${re}`);
});
