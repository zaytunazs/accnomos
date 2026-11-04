import LiveCalendar from "@/components/calendar/LiveCalendar";

export const metadata = { title: "Calendar · Accnomos", robots: { index: false, follow: false } };

export default function CalendarPage() {
  return <LiveCalendar />;
}
