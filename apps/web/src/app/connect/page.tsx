import ConnectMicrosoft from "@/components/ConnectMicrosoft";

export const metadata = { title: "Connect your cloud · Accnomos" };

export default function ConnectPage() {
  return (
    <main className="mx-auto max-w-xl px-4 py-10">
      <p className="text-xs font-bold uppercase tracking-wider text-[#0A4F47]">Step 1 of 4</p>
      <h1 className="mt-1 text-3xl font-extrabold tracking-tight text-[#1B1F24]">Connect your cloud</h1>
      <p className="mt-2 text-[15px] leading-relaxed text-[#4B5159]">
        Your books will live in a folder in your own OneDrive. Accnomos keeps nothing on its servers: sign in
        with Microsoft, and we create the folder in your account.
      </p>
      <ConnectMicrosoft />
    </main>
  );
}
