"use client";
import { QueryClientProvider } from "@tanstack/react-query";
import { queryClient } from "@/services/api";
import WSInitializer from "@/components/common/WSInitializer";

export default function Providers({ children }: { children: React.ReactNode }) {
  return (
    <QueryClientProvider client={queryClient}>
      <WSInitializer />
      {children}
    </QueryClientProvider>
  );
}
