import Sidebar from "@/components/layout/Sidebar";
import GlobalHeader from "@/components/layout/GlobalHeader";
import WSInitializer from "@/components/common/WSInitializer";
import ToastContainer from "@/components/common/ToastContainer";

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="h-screen flex overflow-hidden">
      <Sidebar />
      <div className="flex-1 flex flex-col overflow-hidden">
        <GlobalHeader />
        <main className="flex-1 overflow-auto p-4">{children}</main>
      </div>
      <WSInitializer />
      <ToastContainer />
    </div>
  );
}
