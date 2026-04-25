export function SupersetPage() {
  // Iframe is same-origin via HAProxy at /bi/ (Superset's own blueprints use
  // /superset/* so we can't reuse that prefix externally). SSO happens
  // inside the iframe via the "Sign In with monctl" button on first visit;
  // subsequent visits are seamless as long as the MonCTL session is alive.
  return (
    <div className="h-screen flex flex-col">
      <iframe src="/bi/" title="Superset" className="flex-1 w-full border-0" />
    </div>
  );
}
