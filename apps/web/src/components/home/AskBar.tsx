export default function AskBar() {
  return (
    <form
      method="get"
      action="/ask"
      className="flex items-center gap-2 rounded-2xl border border-border bg-white p-2 pl-4"
    >
      <label htmlFor="home-ask" className="sr-only">
        Ask your books
      </label>
      <input
        id="home-ask"
        name="q"
        type="text"
        placeholder="Ask your books — “how much VAT do I owe and why?”"
        className="min-w-0 flex-1 bg-transparent text-[15px] outline-none placeholder:text-muted"
      />
      <button
        type="button"
        aria-label="Speak"
        disabled
        title="Sign in, then ask by voice on the Ask page"
        className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl text-muted hover:bg-ground disabled:opacity-60"
      >
        <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
          <rect
            x="6"
            y="1.5"
            width="6"
            height="9"
            rx="3"
            stroke="currentColor"
            strokeWidth="1.6"
          />
          <path
            d="M3.5 8.5a5.5 5.5 0 0 0 11 0M9 14v2.5"
            stroke="currentColor"
            strokeWidth="1.6"
            strokeLinecap="round"
          />
        </svg>
      </button>
      <button
        type="submit"
        className="flex h-10 shrink-0 items-center whitespace-nowrap rounded-xl bg-teal px-5 text-[15px] font-bold text-white hover:bg-teal-dark"
      >
        Ask
      </button>
    </form>
  );
}
