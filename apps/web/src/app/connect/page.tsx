import ConnectMicrosoft from "@/components/ConnectMicrosoft";
import ConnectSteps from "@/components/connect/ConnectSteps";

export const metadata = { title: "Connect your cloud · Accnomos" };

export default function ConnectPage() {
  return (
    <div className="mx-auto max-w-xl px-4 py-10">
      <ConnectSteps current={1} />
      <h1 className="mt-4 text-3xl font-extrabold tracking-tight text-[#1B1F24]">Connect your cloud</h1>
      <p className="mt-2 text-[15px] leading-relaxed text-[#4B5159]">
        Your books will live in a folder in your own OneDrive. Accnomos keeps nothing on its servers: sign in
        with Microsoft, and we create the folder in your account.
      </p>
      <ConnectMicrosoft />
    </div>
  );
}
