interface SkeletonProps {
  className?: string;
}

export function SkeletonBlock({ className = "" }: SkeletonProps) {
  return <div className={`skeleton ${className}`} />;
}

export function SkeletonStatCard() {
  return (
    <div className="glass-panel rounded-xl p-5 animate-fade-in-up">
      <div className="flex justify-between items-start mb-4">
        <div className="flex-1">
          <div className="skeleton h-3 w-28 mb-3 rounded" />
          <div className="skeleton h-7 w-36 rounded" />
        </div>
        <div className="skeleton h-6 w-14 rounded" />
      </div>
      <div className="skeleton h-12 w-full rounded" />
    </div>
  );
}

export function SkeletonChart() {
  return (
    <div className="glass-panel rounded-xl flex flex-col overflow-hidden h-full">
      <div className="p-4 border-b border-white/5 flex justify-between items-center">
        <div className="skeleton h-5 w-32 rounded" />
        <div className="skeleton h-6 w-28 rounded" />
      </div>
      <div className="flex-1 p-4 flex flex-col gap-3 justify-end">
        <div className="skeleton h-1 w-full rounded" />
        <div className="skeleton h-1 w-full rounded" />
        <div className="skeleton h-1 w-full rounded" />
        <div className="flex-1 flex items-end gap-1">
          {Array.from({ length: 12 }).map((_, i) => (
            <div
              key={i}
              className="skeleton flex-1 rounded-t"
              style={{ height: `${20 + Math.random() * 60}%` }}
            />
          ))}
        </div>
      </div>
    </div>
  );
}

export function SkeletonTable({ rows = 5 }: { rows?: number }) {
  return (
    <div className="glass-panel rounded-xl flex flex-col overflow-hidden">
      <div className="p-4 border-b border-white/5 flex justify-between items-center">
        <div className="skeleton h-5 w-36 rounded" />
        <div className="skeleton h-6 w-24 rounded" />
      </div>
      <div className="divide-y divide-white/5">
        {Array.from({ length: rows }).map((_, i) => (
          <div key={i} className="px-4 py-3 flex items-center gap-4">
            <div className="skeleton h-8 w-8 rounded-lg shrink-0" />
            <div className="flex-1 flex flex-col gap-1.5">
              <div className="skeleton h-3 w-24 rounded" />
              <div className="skeleton h-2 w-16 rounded" />
            </div>
            <div className="skeleton h-4 w-16 rounded" />
            <div className="skeleton h-4 w-12 rounded" />
          </div>
        ))}
      </div>
    </div>
  );
}
