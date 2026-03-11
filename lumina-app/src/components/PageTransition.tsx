"use client";

import { usePathname } from "next/navigation";
import { useEffect, useState, useRef, type ReactNode } from "react";

interface PageTransitionProps {
  children: ReactNode;
}

export default function PageTransition({ children }: PageTransitionProps) {
  const pathname = usePathname();
  const [isVisible, setIsVisible] = useState(true);
  const prevPathRef = useRef(pathname);

  useEffect(() => {
    // Only animate on actual route changes, not on children re-renders
    if (prevPathRef.current === pathname) return;
    prevPathRef.current = pathname;
    setIsVisible(false);
    const timeout = setTimeout(() => setIsVisible(true), 80);
    return () => clearTimeout(timeout);
  }, [pathname]);

  return (
    <div
      className={`transition-all duration-300 ease-out ${
        isVisible ? "opacity-100 translate-y-0" : "opacity-0 translate-y-2"
      }`}
    >
      {children}
    </div>
  );
}
