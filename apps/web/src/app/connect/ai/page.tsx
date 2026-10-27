import ChooseAi from "@/components/ChooseAi";

export const metadata = { title: "Choose your AI · Accnomos" };

export default function ChooseAiPage() {
  return (
    <div className="mx-auto max-w-xl px-4 py-10">
      <p className="text-xs font-bold uppercase tracking-wider text-[#0A4F47]">Step 2 of 4</p>
      <h1 className="mt-1 text-3xl font-extrabold tracking-tight text-[#1B1F24]">Choose how Meta AI runs your books</h1>
      <p className="mt-2 text-[15px] leading-relaxed text-[#4B5159]">
        Either way, we never see your data. The key or the address stays on this device and goes only to your
        runtime.
      </p>
      <ChooseAi />
    </div>
  );
}
