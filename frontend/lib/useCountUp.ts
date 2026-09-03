import { useEffect, useRef, useState } from "react";

/**
 * Animates a numeric KPI from its previous value to `target` over `duration`ms.
 * Returns `target` unchanged on the first render (no count-up from zero on
 * initial load) and on null (nothing to animate toward).
 */
export function useCountUp(target: number | null, duration = 650): number | null {
  const [value, setValue] = useState<number | null>(target);
  const fromRef = useRef<number | null>(target);
  const frameRef = useRef<number | undefined>(undefined);

  useEffect(() => {
    if (target === null) {
      setValue(null);
      fromRef.current = null;
      return;
    }

    const from = fromRef.current ?? target;
    if (from === target) {
      setValue(target);
      return;
    }

    const start = performance.now();
    const ease = (t: number) => 1 - (1 - t) * (1 - t);

    function tick(now: number) {
      const elapsed = now - start;
      const t = Math.min(1, elapsed / duration);
      setValue(from + (target! - from) * ease(t));
      if (t < 1) {
        frameRef.current = requestAnimationFrame(tick);
      } else {
        fromRef.current = target;
      }
    }

    frameRef.current = requestAnimationFrame(tick);
    return () => {
      if (frameRef.current) cancelAnimationFrame(frameRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [target]);

  return value;
}
