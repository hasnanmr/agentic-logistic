import type { Metadata } from "next";
import type { ReactNode } from "react";

import Nav from "./components/Nav";
import "./globals.css";

export const metadata: Metadata = {
  title: "AI Logistics Analytics",
  description: "Operational logistics analytics and demand forecasting",
};

export default function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <html lang="en">
      <body>
        <Nav />
        {children}
      </body>
    </html>
  );
}
