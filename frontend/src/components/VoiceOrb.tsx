import type { Listening } from "@/lib/state/session";

const CAPTION: Record<Listening, string> = {
  idle: "Ready",
  listening: "Listening…",
  processing: "Thinking…",
  speaking: "Nakshatra is speaking",
};

/**
 * The only voice visual (design brief): a cloudy indigo sphere, breathing while
 * listening, dimmed with a pulsing ring while thinking, swirling faster while
 * speaking. No waveform, no bars.
 */
export function VoiceOrb({ state, size = 220 }: { state: Listening; size?: number }) {
  return (
    <div className="orb-wrap" data-state={state} style={{ width: size, height: size }}>
      <div className="orb__glow" />
      <div className="orb__halo" />
      <div className="orb__ring" />
      <div className="orb" role="img" aria-label={CAPTION[state]}>
        <svg className="orb__wisps orb__wisps--a" viewBox="0 0 200 200" fill="none" aria-hidden>
          <path
            d="M20 90C45 60 95 65 110 95C125 125 170 130 185 105C195 85 180 40 145 35C110 30 75 45 45 65"
            opacity="0.4"
            stroke="#FFFFFF"
            strokeDasharray="8 14"
            strokeLinecap="round"
            strokeWidth="14"
          />
          <path
            d="M30 120C60 145 100 135 125 115C150 95 175 110 180 135"
            opacity="0.5"
            stroke="#E0E7FF"
            strokeLinecap="round"
            strokeWidth="18"
          />
        </svg>
        <svg className="orb__wisps orb__wisps--b" viewBox="0 0 200 200" fill="none" aria-hidden>
          <path
            d="M40 70C70 50 120 70 140 100C160 130 130 160 95 155C60 150 45 120 50 95"
            stroke="#FFFFFF"
            strokeDasharray="12 18"
            strokeLinecap="round"
            strokeWidth="12"
          />
        </svg>
        <div className="orb__sheen" />
      </div>
    </div>
  );
}

export function orbCaption(state: Listening): string {
  return CAPTION[state];
}
