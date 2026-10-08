// @ts-nocheck
// Animated Characters Login Component
// Source: https://github.com/arsh342/careercompass (MIT License)
// Adapted for React (non-Next.js) - Performance optimized

import { useState, useEffect, useRef, useCallback } from "react";

// ============================================================
// 全局鼠标位置管理（单一监听器，所有组件共享）
// ============================================================
let globalMouseX = 0;
let globalMouseY = 0;
let rafId: number | null = null;
const mouseSubscribers = new Set<() => void>();

function addMouseSubscriber(callback: () => void) {
  if (mouseSubscribers.size === 0) {
    const handleMouseMove = (e: MouseEvent) => {
      globalMouseX = e.clientX;
      globalMouseY = e.clientY;
      if (rafId === null) {
        rafId = requestAnimationFrame(() => {
          mouseSubscribers.forEach(cb => cb());
          rafId = null;
        });
      }
    };
    window.addEventListener("mousemove", handleMouseMove, { passive: true });
    (addMouseSubscriber as any)._cleanup = () => {
      window.removeEventListener("mousemove", handleMouseMove);
    };
  }
  mouseSubscribers.add(callback);
  return () => {
    mouseSubscribers.delete(callback);
    if (mouseSubscribers.size === 0) {
      if (rafId !== null) {
        cancelAnimationFrame(rafId);
        rafId = null;
      }
      (addMouseSubscriber as any)._cleanup?.();
    }
  };
}

// ============================================================
// Pupil 组件（纯瞳孔，无白色眼球）
// ============================================================
interface PupilProps {
  size?: number;
  maxDistance?: number;
  pupilColor?: string;
  forceLookX?: number;
  forceLookY?: number;
}

export const Pupil = ({
  size = 12,
  maxDistance = 5,
  pupilColor = "black",
  forceLookX,
  forceLookY,
}: PupilProps) => {
  const [pos, setPos] = useState({ x: 0, y: 0 });
  const pupilRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (forceLookX !== undefined && forceLookY !== undefined) {
      setPos({ x: forceLookX, y: forceLookY });
      return;
    }

    const update = () => {
      if (!pupilRef.current) return;
      const rect = pupilRef.current.getBoundingClientRect();
      const cx = rect.left + rect.width / 2;
      const cy = rect.top + rect.height / 2;
      const dx = globalMouseX - cx;
      const dy = globalMouseY - cy;
      const dist = Math.min(Math.sqrt(dx * dx + dy * dy), maxDistance);
      const angle = Math.atan2(dy, dx);
      setPos({ x: Math.cos(angle) * dist, y: Math.sin(angle) * dist });
    };

    return addMouseSubscriber(update);
  }, [forceLookX, forceLookY, maxDistance]);

  return (
    <div
      ref={pupilRef}
      className="rounded-full"
      style={{
        width: size,
        height: size,
        backgroundColor: pupilColor,
        transform: `translate(${pos.x}px, ${pos.y}px)`,
        transition: "transform 0.08s linear",
        willChange: "transform",
      }}
    />
  );
};

// ============================================================
// EyeBall 组件（白色眼球 + 瞳孔）
// ============================================================
interface EyeBallProps {
  size?: number;
  pupilSize?: number;
  maxDistance?: number;
  eyeColor?: string;
  pupilColor?: string;
  isBlinking?: boolean;
  forceLookX?: number;
  forceLookY?: number;
}

export const EyeBall = ({
  size = 48,
  pupilSize = 16,
  maxDistance = 10,
  eyeColor = "white",
  pupilColor = "black",
  isBlinking = false,
  forceLookX,
  forceLookY,
}: EyeBallProps) => {
  const [pos, setPos] = useState({ x: 0, y: 0 });
  const eyeRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (forceLookX !== undefined && forceLookY !== undefined) {
      setPos({ x: forceLookX, y: forceLookY });
      return;
    }

    const update = () => {
      if (!eyeRef.current) return;
      const rect = eyeRef.current.getBoundingClientRect();
      const cx = rect.left + rect.width / 2;
      const cy = rect.top + rect.height / 2;
      const dx = globalMouseX - cx;
      const dy = globalMouseY - cy;
      const dist = Math.min(Math.sqrt(dx * dx + dy * dy), maxDistance);
      const angle = Math.atan2(dy, dx);
      setPos({ x: Math.cos(angle) * dist, y: Math.sin(angle) * dist });
    };

    return addMouseSubscriber(update);
  }, [forceLookX, forceLookY, maxDistance]);

  return (
    <div
      ref={eyeRef}
      className="rounded-full flex items-center justify-center"
      style={{
        width: size,
        height: isBlinking ? 2 : size,
        backgroundColor: eyeColor,
        overflow: "hidden",
        transition: "height 0.1s ease",
      }}
    >
      {!isBlinking && (
        <div
          className="rounded-full"
          style={{
            width: pupilSize,
            height: pupilSize,
            backgroundColor: pupilColor,
            transform: `translate(${pos.x}px, ${pos.y}px)`,
            transition: "transform 0.08s linear",
            willChange: "transform",
          }}
        />
      )}
    </div>
  );
};

// ============================================================
// AnimatedCharacters 主组件
// ============================================================
interface AnimatedCharactersProps {
  isTyping?: boolean;
  showPassword?: boolean;
  passwordLength?: number;
}

export function AnimatedCharacters({
  isTyping = false,
  showPassword = false,
  passwordLength = 0,
}: AnimatedCharactersProps) {
  const [mousePos, setMousePos] = useState({ x: 0, y: 0 });
  const [isPurpleBlinking, setIsPurpleBlinking] = useState(false);
  const [isBlackBlinking, setIsBlackBlinking] = useState(false);
  const [isLookingAtEachOther, setIsLookingAtEachOther] = useState(false);
  const [isPurplePeeking, setIsPurplePeeking] = useState(false);
  const purpleRef = useRef<HTMLDivElement>(null);
  const blackRef = useRef<HTMLDivElement>(null);
  const yellowRef = useRef<HTMLDivElement>(null);
  const orangeRef = useRef<HTMLDivElement>(null);

  // 单一鼠标订阅
  useEffect(() => {
    return addMouseSubscriber(() => {
      setMousePos({ x: globalMouseX, y: globalMouseY });
    });
  }, []);

  // 眨眼效果 - 紫色角色
  useEffect(() => {
    let timeout: ReturnType<typeof setTimeout>;
    const scheduleBlink = () => {
      timeout = setTimeout(() => {
        setIsPurpleBlinking(true);
        setTimeout(() => {
          setIsPurpleBlinking(false);
          scheduleBlink();
        }, 150);
      }, Math.random() * 4000 + 3000);
    };
    scheduleBlink();
    return () => clearTimeout(timeout);
  }, []);

  // 眨眼效果 - 黑色角色
  useEffect(() => {
    let timeout: ReturnType<typeof setTimeout>;
    const scheduleBlink = () => {
      timeout = setTimeout(() => {
        setIsBlackBlinking(true);
        setTimeout(() => {
          setIsBlackBlinking(false);
          scheduleBlink();
        }, 150);
      }, Math.random() * 4000 + 3000);
    };
    scheduleBlink();
    return () => clearTimeout(timeout);
  }, []);

  // 互相看动画
  useEffect(() => {
    if (isTyping) {
      setIsLookingAtEachOther(true);
      const timer = setTimeout(() => setIsLookingAtEachOther(false), 800);
      return () => clearTimeout(timer);
    } else {
      setIsLookingAtEachOther(false);
    }
  }, [isTyping]);

  // 紫色偷看动画
  useEffect(() => {
    if (passwordLength > 0 && showPassword) {
      const timeout = setTimeout(() => {
        setIsPurplePeeking(true);
        setTimeout(() => setIsPurplePeeking(false), 800);
      }, Math.random() * 3000 + 2000);
      return () => clearTimeout(timeout);
    } else {
      setIsPurplePeeking(false);
    }
  }, [passwordLength, showPassword, isPurplePeeking]);

  // 计算角色位置偏移
  const calculatePosition = useCallback(
    (ref: React.RefObject<HTMLDivElement | null>) => {
      if (!ref.current) return { faceX: 0, faceY: 0, bodySkew: 0 };
      const rect = ref.current.getBoundingClientRect();
      const centerX = rect.left + rect.width / 2;
      const centerY = rect.top + rect.height / 3;
      const deltaX = mousePos.x - centerX;
      const deltaY = mousePos.y - centerY;
      return {
        faceX: Math.max(-12, Math.min(12, deltaX / 25)),
        faceY: Math.max(-8, Math.min(8, deltaY / 35)),
        bodySkew: Math.max(-5, Math.min(5, -deltaX / 150)),
      };
    },
    [mousePos.x, mousePos.y]
  );

  const purplePos = calculatePosition(purpleRef);
  const blackPos = calculatePosition(blackRef);
  const yellowPos = calculatePosition(yellowRef);
  const orangePos = calculatePosition(orangeRef);

  const isHidingPassword = passwordLength > 0 && !showPassword;

  return (
    <div className="relative w-full h-full max-w-[420px] max-h-[320px] mx-auto">
      {/* 紫色高个角色 - 后层 */}
      <div
        ref={purpleRef}
        className="absolute bottom-0"
        style={{
          left: "12%",
          width: "35%",
          height: isTyping || isHidingPassword ? "110%" : "100%",
          backgroundColor: "#6C3FF5",
          borderRadius: "10px 10px 0 0",
          zIndex: 1,
          transform:
            passwordLength > 0 && showPassword
              ? "skewX(0deg)"
              : isTyping || isHidingPassword
              ? `skewX(${(purplePos.bodySkew || 0) - 8}deg) translateX(25px)`
              : `skewX(${purplePos.bodySkew || 0}deg)`,
          transformOrigin: "bottom center",
          transition: "transform 0.35s cubic-bezier(0.4, 0, 0.2, 1), height 0.35s cubic-bezier(0.4, 0, 0.2, 1)",
          willChange: "transform",
        }}
      >
        <div
          className="absolute flex gap-6"
          style={{
            left:
              passwordLength > 0 && showPassword
                ? "12%"
                : isLookingAtEachOther
                ? "32%"
                : `${26 + purplePos.faceX}%`,
            top:
              passwordLength > 0 && showPassword
                ? "9%"
                : isLookingAtEachOther
                ? "16%"
                : `${10 + purplePos.faceY}%`,
            transition: "left 0.25s ease-out, top 0.25s ease-out",
          }}
        >
          <EyeBall
            size={16}
            pupilSize={6}
            maxDistance={4}
            eyeColor="white"
            pupilColor="#2D2D2D"
            isBlinking={isPurpleBlinking}
            forceLookX={
              passwordLength > 0 && showPassword
                ? isPurplePeeking ? 3 : -3
                : isLookingAtEachOther ? 3 : undefined
            }
            forceLookY={
              passwordLength > 0 && showPassword
                ? isPurplePeeking ? 4 : -3
                : isLookingAtEachOther ? 3 : undefined
            }
          />
          <EyeBall
            size={16}
            pupilSize={6}
            maxDistance={4}
            eyeColor="white"
            pupilColor="#2D2D2D"
            isBlinking={isPurpleBlinking}
            forceLookX={
              passwordLength > 0 && showPassword
                ? isPurplePeeking ? 3 : -3
                : isLookingAtEachOther ? 3 : undefined
            }
            forceLookY={
              passwordLength > 0 && showPassword
                ? isPurplePeeking ? 4 : -3
                : isLookingAtEachOther ? 3 : undefined
            }
          />
        </div>
      </div>

      {/* 黑色角色 - 中层 */}
      <div
        ref={blackRef}
        className="absolute bottom-0"
        style={{
          left: "44%",
          width: "24%",
          height: "78%",
          backgroundColor: "#2D2D2D",
          borderRadius: "8px 8px 0 0",
          zIndex: 2,
          transform:
            passwordLength > 0 && showPassword
              ? "skewX(0deg)"
              : isLookingAtEachOther
              ? `skewX(${(blackPos.bodySkew || 0) * 1.5 + 8}deg) translateX(12px)`
              : isTyping || isHidingPassword
              ? `skewX(${(blackPos.bodySkew || 0) * 1.5}deg)`
              : `skewX(${blackPos.bodySkew || 0}deg)`,
          transformOrigin: "bottom center",
          transition: "transform 0.35s cubic-bezier(0.4, 0, 0.2, 1)",
          willChange: "transform",
        }}
      >
        <div
          className="absolute flex gap-5"
          style={{
            left:
              passwordLength > 0 && showPassword
                ? "10%"
                : isLookingAtEachOther
                ? "28%"
                : `${22 + blackPos.faceX}%`,
            top:
              passwordLength > 0 && showPassword
                ? "9%"
                : isLookingAtEachOther
                ? "4%"
                : `${10 + blackPos.faceY}%`,
            transition: "left 0.25s ease-out, top 0.25s ease-out",
          }}
        >
          <EyeBall
            size={14}
            pupilSize={5}
            maxDistance={3}
            eyeColor="white"
            pupilColor="#2D2D2D"
            isBlinking={isBlackBlinking}
            forceLookX={
              passwordLength > 0 && showPassword ? -3 : isLookingAtEachOther ? 0 : undefined
            }
            forceLookY={
              passwordLength > 0 && showPassword ? -3 : isLookingAtEachOther ? -3 : undefined
            }
          />
          <EyeBall
            size={14}
            pupilSize={5}
            maxDistance={3}
            eyeColor="white"
            pupilColor="#2D2D2D"
            isBlinking={isBlackBlinking}
            forceLookX={
              passwordLength > 0 && showPassword ? -3 : isLookingAtEachOther ? 0 : undefined
            }
            forceLookY={
              passwordLength > 0 && showPassword ? -3 : isLookingAtEachOther ? -3 : undefined
            }
          />
        </div>
      </div>

      {/* 橙色半圆角色 - 前左 */}
      <div
        ref={orangeRef}
        className="absolute bottom-0"
        style={{
          left: "0%",
          width: "46%",
          height: "52%",
          backgroundColor: "#FF9B6B",
          borderRadius: "50% 50% 0 0",
          zIndex: 3,
          transform:
            passwordLength > 0 && showPassword
              ? "skewX(0deg)"
              : `skewX(${orangePos.bodySkew || 0}deg)`,
          transformOrigin: "bottom center",
          transition: "transform 0.3s cubic-bezier(0.4, 0, 0.2, 1)",
          willChange: "transform",
        }}
      >
        <div
          className="absolute flex gap-6"
          style={{
            left:
              passwordLength > 0 && showPassword
                ? "22%"
                : `${35 + (orangePos.faceX || 0)}%`,
            top:
              passwordLength > 0 && showPassword
                ? "45%"
                : `${45 + (orangePos.faceY || 0)}%`,
            transition: "left 0.15s ease-out, top 0.15s ease-out",
          }}
        >
          <Pupil
            size={10}
            maxDistance={4}
            pupilColor="#2D2D2D"
            forceLookX={passwordLength > 0 && showPassword ? -4 : undefined}
            forceLookY={passwordLength > 0 && showPassword ? -3 : undefined}
          />
          <Pupil
            size={10}
            maxDistance={4}
            pupilColor="#2D2D2D"
            forceLookX={passwordLength > 0 && showPassword ? -4 : undefined}
            forceLookY={passwordLength > 0 && showPassword ? -3 : undefined}
          />
        </div>
      </div>

      {/* 黄色角色 - 前右 */}
      <div
        ref={yellowRef}
        className="absolute bottom-0"
        style={{
          left: "58%",
          width: "30%",
          height: "60%",
          backgroundColor: "#E8D754",
          borderRadius: "50% 50% 0 0",
          zIndex: 4,
          transform:
            passwordLength > 0 && showPassword
              ? "skewX(0deg)"
              : `skewX(${yellowPos.bodySkew || 0}deg)`,
          transformOrigin: "bottom center",
          transition: "transform 0.3s cubic-bezier(0.4, 0, 0.2, 1)",
          willChange: "transform",
        }}
      >
        <div
          className="absolute flex gap-4"
          style={{
            left:
              passwordLength > 0 && showPassword
                ? "18%"
                : `${38 + (yellowPos.faceX || 0)}%`,
            top:
              passwordLength > 0 && showPassword
                ? "18%"
                : `${18 + (yellowPos.faceY || 0)}%`,
            transition: "left 0.15s ease-out, top 0.15s ease-out",
          }}
        >
          <Pupil
            size={10}
            maxDistance={4}
            pupilColor="#2D2D2D"
            forceLookX={passwordLength > 0 && showPassword ? -4 : undefined}
            forceLookY={passwordLength > 0 && showPassword ? -3 : undefined}
          />
          <Pupil
            size={10}
            maxDistance={4}
            pupilColor="#2D2D2D"
            forceLookX={passwordLength > 0 && showPassword ? -4 : undefined}
            forceLookY={passwordLength > 0 && showPassword ? -3 : undefined}
          />
        </div>
        {/* 嘴巴 */}
        <div
          className="absolute h-[3px] bg-[#2D2D2D] rounded-full"
          style={{
            width: "50%",
            left:
              passwordLength > 0 && showPassword
                ? "10%"
                : `${30 + (yellowPos.faceX || 0)}%`,
            top:
              passwordLength > 0 && showPassword
                ? "45%"
                : `${42 + (yellowPos.faceY || 0)}%`,
            transition: "left 0.15s ease-out, top 0.15s ease-out",
          }}
        />
      </div>
    </div>
  );
}
