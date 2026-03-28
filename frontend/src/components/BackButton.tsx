import { useNavigate } from "react-router-dom";

export default function BackButton({ fallback = "/" }: { fallback?: string }) {
  const navigate = useNavigate();

  function handleBack() {
    if (window.history.length > 1) {
      navigate(-1);
      return;
    }
    navigate(fallback);
  }

  return (
    <button
      onClick={handleBack}
      className="crt-action font-retro text-xl tracking-widest text-zinc-500 transition-colors hover:text-zinc-200"
    >
      <span className="crt-action__label" data-text="◀ BACK">
        ◀ BACK
      </span>
    </button>
  );
}
