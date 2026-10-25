// Heading kiểu teamtechvibe: nhãn eyebrow (dot + mono tracking) + heading lớn
// với từ nhấn serif italic (accent-italic trong index.css).
export default function SectionHead({ eyebrow, title }: { eyebrow: string; title: React.ReactNode }) {
  return (
    <div className="pt-7">
      <p className="flex items-center gap-2 font-mono text-[11px] tracking-[0.18em] text-mute font-medium">
        <span className="w-1.5 h-1.5 rounded-full bg-peri inline-block" aria-hidden />
        {eyebrow}
      </p>
      <h2 className="mt-2 text-[26px] md:text-[30px] font-extrabold tracking-tight leading-tight">{title}</h2>
    </div>
  );
}
