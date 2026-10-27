import ExplainMore from "@/components/ExplainMore";
import LiveVehicles from "@/components/vehicles/LiveVehicles";

export default function VehiclesPage() {
  return (
    <div className="flex flex-col gap-5">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-3xl font-extrabold tracking-tight">Vehicles &amp; mileage</h1>
          <p className="mt-1 text-[15px] leading-7 text-muted">
            Log business journeys, see the HMRC approved mileage allowance build up, and claim it a quarter at a time.
            Figures are calculated by code; claims wait in Review for you to approve.
          </p>
        </div>
        <ExplainMore title="How mileage claims work" anchor="vehicles">
          Allowances come from one HMRC rate table in code (45p/25p, 24p, 20p). A quarterly claim is a proposal you approve in Review, never automatic, and claimed journeys lock until the claim is undone.
        </ExplainMore>
      </div>
      <LiveVehicles />
    </div>
  );
}
