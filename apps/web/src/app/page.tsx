import { TodayDashboard } from "@/components/today-dashboard";

export default function Home() {
  return (
    <main id="main-content" tabIndex={-1} className="page today-page">
      <TodayDashboard />
    </main>
  );
}
