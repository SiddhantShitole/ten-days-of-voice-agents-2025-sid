import React, { useState } from 'react';
import { Button } from '@/components/livekit/button';

// Hero / Logo Icon
function HeroIcon() {
  return (
    <svg
      width="64"
      height="64"
      viewBox="0 0 64 64"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className="text-white mb-6 drop-shadow-[0_0_25px_rgba(255,255,255,0.7)] relative z-10 animate-pulse-slow"
    >
      <path
        d="M15 24V40C15 40.7957 14.6839 41.5587 14.1213 42.1213C13.5587 42.6839 12.7956 43 12 43C11.2044 43 10.4413 42.6839 9.87868 42.1213C9.31607 41.5587 9 40.7957 9 40V24C9 23.2044 9.31607 22.4413 9.87868 21.8787C10.4413 21.3161 11.2044 21 12 21C12.7956 21 13.5587 21.3161 14.1213 21.8787C14.6839 22.4413 15 23.2044 15 24ZM22 5C21.2044 5 20.4413 5.31607 19.8787 5.87868C19.3161 6.44129 19 7.20435 19 8V56C19 56.7957 19.3161 57.5587 19.8787 58.1213C20.4413 58.6839 21.2044 59 22 59C22.7956 59 23.5587 58.6839 24.1213 58.1213C24.6839 57.5587 25 56.7957 25 56V8C25 7.20435 24.6839 6.44129 24.1213 5.87868C23.5587 5.31607 22.7956 5 22 5ZM32 13C31.2044 13 30.4413 13.3161 29.8787 13.8787C29.3161 14.4413 29 15.2044 29 16V48C29 48.7957 29.3161 49.5587 29.8787 50.1213C30.4413 50.6839 31.2044 51 32 51C32.7956 51 33.5587 50.6839 34.1213 50.1213C34.6839 49.5587 35 48.7957 35 48V16C35 15.2044 34.6839 14.4413 34.1213 13.8787C33.5587 13.3161 32.7956 13 32 13ZM42 21C41.2043 21 40.4413 21.3161 39.8787 21.8787C39.3161 22.4413 39 23.2044 39 24V40C39 40.7957 39.3161 41.5587 39.8787 42.1213C40.4413 42.6839 41.2043 43 42 43C42.7957 43 43.5587 42.6839 44.1213 42.1213C44.6839 41.5587 45 40.7957 45 40V24C45 23.2044 44.6839 22.4413 44.1213 21.8787C43.5587 21.3161 42.7957 21 42 21ZM52 17C51.2043 17 50.4413 17.3161 49.8787 17.8787C49.3161 18.4413 49 19.2044 49 20V44C49 44.7957 49.3161 45.5587 49.8787 46.1213C50.4413 46.6839 51.2043 47 52 47C52.7957 47 53.5587 46.6839 54.1213 46.1213C54.6839 45.5587 55 44.7957 55 44V20C55 19.2044 54.6839 18.4413 54.1213 17.8787C53.5587 17.3161 52.7957 17 52 17Z"
        fill="currentColor"
      />
    </svg>
  );
}

// Gaming floating icons
function GameIcon({ emoji, style }: { emoji: string; style?: React.CSSProperties }) {
  return (
    <div
      className="absolute text-2xl pointer-events-none select-none animate-float"
      style={{ ...style }}
    >
      {emoji}
    </div>
  );
}

export const WelcomeView = React.forwardRef<HTMLDivElement, any>(
  ({ startButtonText, onStartCall }, ref) => {
    const [name, setName] = useState('');
    const [started, setStarted] = useState(false);

    const handleStart = () => {
      setStarted(true);
      onStartCall?.(name.trim());
    };

    return (
      <div
        ref={ref}
        className="relative flex items-center justify-center min-h-screen w-full overflow-hidden bg-gradient-to-br from-[#0c0c0c] to-[#1a1a1a] px-4"
      >
        {/* Neon moving background blobs */}
        <div className="absolute w-[300px] h-[300px] bg-purple-600/30 rounded-full top-10 left-10 blur-3xl animate-blob"></div>
        <div className="absolute w-[200px] h-[200px] bg-cyan-400/30 rounded-full bottom-20 right-20 blur-2xl animate-blob animation-delay-2000"></div>

        {/* Floating gaming icons */}
        <GameIcon emoji="🗡️" style={{ top: '15%', left: '10%', fontSize: '1.5rem', animationDelay: '0s' }} />
        <GameIcon emoji="🛡️" style={{ top: '40%', left: '80%', fontSize: '2rem', animationDelay: '1.5s' }} />
        <GameIcon emoji="🎲" style={{ top: '60%', left: '20%', fontSize: '1.8rem', animationDelay: '3s' }} />
        <GameIcon emoji="🎮" style={{ top: '25%', left: '50%', fontSize: '2rem', animationDelay: '2s' }} />
        <GameIcon emoji="🪄" style={{ top: '70%', left: '70%', fontSize: '1.6rem', animationDelay: '4s' }} />

        {!started ? (
          <div className="relative bg-[#1a1a1a] rounded-3xl p-8 flex flex-col items-center text-center max-w-sm w-full shadow-[0_0_60px_rgba(124,58,237,0.3),inset_8px_8px_16px_#0d0d0d,inset_-8px_-8px_16px_#272727] border border-white/10 z-10">
            <HeroIcon />
            <h2 className="text-2xl font-bold mb-2 drop-shadow-lg tracking-tight">
              Ready to Enter the Neon Arena?
            </h2>
            <p className="text-white/80 font-medium leading-6 mb-6">
              Enter your stage name to join the battle
            </p>

            <div className="w-full flex flex-col gap-3">
              <label className="text-xs uppercase text-white/60 font-bold tracking-wide ml-1">
                Stage Name
              </label>
              <div className="flex gap-2 w-full">
                <input
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && handleStart()}
                  placeholder="Enter name..."
                  className="flex-1 px-4 py-3 rounded-xl bg-[#1a1a1a] text-white font-semibold placeholder:text-white/40 shadow-[inset_0_0_15px_#7c3aed,inset_0_0_10px_#0d0d0d] focus:outline-none focus:ring-2 focus:ring-purple-400/70 transition-all"
                />
                <Button
                  onClick={handleStart}
                  className="px-6 font-bold rounded-xl bg-gradient-to-r from-green-400 to-green-500 text-blue-900 hover:from-black-300 hover:to-green-400 shadow-lg transform hover:scale-[1.05] transition-all flex items-center justify-center"
                >
                  Enter
                </Button>
              </div>
            </div>

            <div className="mt-4 text-[10px] text-white/40 uppercase tracking-widest font-mono">
              Press Enter to Start
            </div>
          </div>
        ) : (
          <div className="text-white text-2xl font-bold animate-pulse drop-shadow-lg text-center z-10">
            🔥 Neon Arena loading…
          </div>
        )}
      </div>
    );
  }
);

WelcomeView.displayName = 'WelcomeView';
