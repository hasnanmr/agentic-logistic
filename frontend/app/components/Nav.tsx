"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const LINKS = [
  { href: "/", label: "Dashboard" },
  { href: "/ask", label: "Ask Operations" },
];

export default function Nav() {
  const pathname = usePathname();

  return (
    <header className="nav">
      <div className="nav-inner">
        <span className="nav-brand">AI Logistics Analytics</span>
        <nav className="nav-links">
          {LINKS.map((link) => (
            <Link
              key={link.href}
              href={link.href}
              className={pathname === link.href ? "nav-link active" : "nav-link"}
            >
              {link.label}
            </Link>
          ))}
        </nav>
      </div>
    </header>
  );
}
