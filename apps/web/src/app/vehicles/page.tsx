import LiveVehicles from "@/components/vehicles/LiveVehicles";

export default function VehiclesPage() {
  return (
    <div className="flex flex-col gap-5">
      <div>
        <h1 className="text-3xl font-extrabold tracking-tight">Vehicles &amp; mileage</h1>
        <p className="mt-1 text-[15px] leading-7 text-muted">
          Log business journeys, see the HMRC approved mileage allowance build up, and claim it a quarter at a time.
          Figures are calculated by code; claims wait in Review for you to approve.
        </p>
      </div>
      <LiveVehicles />
    </div>
  );
}
