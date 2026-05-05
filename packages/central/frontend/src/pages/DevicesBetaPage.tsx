import { Link } from "react-router-dom";

export function DevicesBetaPage() {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-3 text-zinc-400">
      <p className="text-2xl font-semibold text-zinc-200">Devices (beta)</p>
      <p className="max-w-md text-center text-sm">
        Redesigned Devices list with saved views, status filter pills, and an
        in-place selection action bar. Coming soon.
      </p>
      <Link
        to="/devices"
        className="text-sm text-brand-400 hover:text-brand-300 transition-colors"
      >
        ← Switch to classic
      </Link>
    </div>
  );
}
