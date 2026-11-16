// Logo "Săn Việc" — thấu kính soi chiếc cặp: nghĩa đen của săn việc.
// Theo design language vibe-hunt: squircle trắng viền ink + đổ cứng, lens
// gradient periwinkle, tay cầm coral. Vẽ SVG thuần để sắc ở mọi size (favicon
// 16px → hero 96px) và tự đổi màu theo theme.
export default function Logo({ size = 32, shadow = true, className = "" }: {
  size?: number; shadow?: boolean; className?: string;
}) {
  return (
    <svg width={size} height={size} viewBox="0 0 64 64" fill="none" role="img"
      aria-label="Job Hunt" className={className}>
      <defs>
        <linearGradient id="sv-lens" x1="18" y1="16" x2="42" y2="42" gradientUnits="userSpaceOnUse">
          <stop stopColor="#5566ff" />
          <stop offset="1" stopColor="#4353e8" />
        </linearGradient>
      </defs>
      {/* đổ cứng neo-brutalist */}
      {shadow && <rect x="7" y="7" width="55" height="55" rx="17" fill="#181c40" />}
      {/* nền squircle */}
      <rect x="4" y="4" width="55" height="55" rx="17" fill="#ffffff" stroke="#181c40" strokeWidth="3" />
      {/* tay cầm thấu kính */}
      <path d="M40.5 40.5 L51 51" stroke="#ee5238" strokeWidth="7" strokeLinecap="round" />
      {/* vòng lens */}
      <circle cx="29" cy="29" r="15" fill="#eef0ff" stroke="url(#sv-lens)" strokeWidth="5.5" />
      {/* chiếc cặp bên trong lens */}
      <rect x="21.5" y="25.5" width="15" height="10.5" rx="2.6" fill="#5566ff" stroke="#181c40" strokeWidth="2" />
      <path d="M26.5 25.5v-2.2a2.5 2.5 0 0 1 2.5-2.3h0a2.5 2.5 0 0 1 2.5 2.3v2.2"
        stroke="#ee5238" strokeWidth="2.2" strokeLinecap="round" />
      <path d="M21.5 30.2h15" stroke="#eef0ff" strokeWidth="1.6" />
    </svg>
  );
}
