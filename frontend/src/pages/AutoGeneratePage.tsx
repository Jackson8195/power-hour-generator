import { useNavigate } from "react-router-dom";

export default function AutoGeneratePage() {
  const navigate = useNavigate();

  return (
    <div className="relative flex min-h-screen flex-col items-center justify-center overflow-hidden bg-[#0a0a0a] scanlines">
      {/* CRT flicker overlay */}
      <div className="pointer-events-none fixed inset-0 animate-crt-flicker bg-transparent" />

      <div className="relative z-10 flex flex-col items-center gap-4 text-center">
        <h1 className="font-retro text-5xl tracking-widest text-brand-400 glow-text sm:text-6xl">
          AI GENERATION
        </h1>
        <p className="font-retro text-2xl tracking-widest text-zinc-400 animate-pulse">
          — INITIALIZING... —
        </p>
        <p className="font-retro text-sm tracking-widest text-zinc-600">
          COMING SOON
        </p>
      </div>

      <button
        onClick={() => navigate("/")}
        className="absolute bottom-10 font-retro text-xl tracking-widest text-zinc-500 transition-colors hover:text-zinc-200"
      >
        ◀ BACK TO MENU
      </button>
    </div>
  );
}
