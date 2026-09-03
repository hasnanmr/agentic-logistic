import type { Metadata } from "next";
import { Inter } from "next/font/google";
import type { ReactNode } from "react";

import Nav from "./components/Nav";
import "./globals.css";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-sans",
  display: "swap",
});

export const metadata: Metadata = {
  title: "AI Logistics Analytics",
  description: "Operational logistics analytics and demand forecasting",
};

export default function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <html lang="en" className={inter.variable}>
      <body>
        <Nav />
        {children}
      </body>
    </html>
  );
}
