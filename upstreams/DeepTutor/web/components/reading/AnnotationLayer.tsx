"use client";

import type { AnnotationItem, NormalisedRect } from "@/lib/reading-api";
import { useTranslation } from "react-i18next";
import Tooltip from "@/shared/ui/Tooltip";

/** Ink for each palette colour, tuned to stay readable over black-on-white text. */
const COLOR_INK: Record<string, string> = {
  yellow: "250 220 90",
  green: "140 219 148",
  blue: "122 192 250",
  pink: "250 161 199",
  purple: "199 174 250",
};

function colorWithOpacity(color: string, opacity: number): string {
  const hex = /^#([a-f\d]{6})([a-f\d]{2})?$/i.exec(color);
  if (hex) {
    const value = hex[1];
    const alpha = hex[2] ? Number.parseInt(hex[2], 16) / 255 : 1;
    const red = Number.parseInt(value.slice(0, 2), 16);
    const green = Number.parseInt(value.slice(2, 4), 16);
    const blue = Number.parseInt(value.slice(4, 6), 16);
    return `rgb(${red} ${green} ${blue} / ${opacity * alpha})`;
  }
  return `rgb(${COLOR_INK[color] ?? COLOR_INK.yellow} / ${opacity})`;
}

export interface InkOverlayStroke {
    stroke_id: string;
    locator?: number;
    tool: "pen" | "highlighter";
    color: string;
    width: number;
    points: Array<[number, number]>;
}

export interface AnnotationLayerProps {
  annotations: AnnotationItem[];
  /** Read-only Pencil ink transformed from canonical PDF coordinates. */
  inkStrokes?: InkOverlayStroke[];
  highlightedAnnotationId?: string | null;
  flashRects?: NormalisedRect[];
  onAnnotationClick?: (annotation: AnnotationItem) => void;
}

/**
 * Overlay that paints stored marks over one rendered unit.
 *
 * Positioned entirely in percentages from the annotation's normalised rects, so
 * it needs no measurement and stays correct through zoom and pane resizing.
 *
 * `multiply` blending is what makes a highlight look like a highlighter rather
 * than a coloured box on top of the words: the text below stays fully legible
 * instead of being tinted.
 *
 * The layer itself is click-through (`pointer-events-none`); only the marks take
 * clicks, so highlighting never blocks text selection on the layer beneath.
 */
export function AnnotationLayer({
  annotations,
  inkStrokes = [],
  highlightedAnnotationId,
  flashRects,
  onAnnotationClick,
}: AnnotationLayerProps) {
  const { t } = useTranslation();
  return (
    <div className="pointer-events-none absolute inset-0">
      {inkStrokes.length > 0 && (
        <svg
          aria-label={t("Ink annotations")}
          className="pointer-events-none absolute inset-0 h-full w-full"
          viewBox="0 0 1 1"
          preserveAspectRatio="none"
        >
          {inkStrokes.map((stroke) => (
            <polyline
              key={stroke.stroke_id}
              points={stroke.points.map(([x, y]) => `${x},${y}`).join(" ")}
              fill="none"
              stroke={stroke.color}
              strokeWidth={stroke.width}
              strokeOpacity={stroke.tool === "highlighter" ? 0.45 : 1}
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          ))}
        </svg>
      )}
      {annotations.map((annotation) =>
        annotation.rects.map((rect, index) => {
          const [x0, y0, x1, y1] = rect;
          const isFocused =
            annotation.annotation_id === highlightedAnnotationId;
          const isUnderline = annotation.kind === "underline";
          const label =
            annotation.note ||
            annotation.quote ||
            t(
              annotation.kind === "citation"
                ? "Citation"
                : isUnderline
                  ? "Underline"
                  : "Highlight",
            );
          return (
            <span
              key={`${annotation.annotation_id}-${index}`}
              className={[
                "pointer-events-auto absolute cursor-pointer transition-[box-shadow,filter] duration-150 [&>span]:h-full [&>span]:w-full [&>span>button]:h-full [&>span>button]:w-full",
                isUnderline ? "" : "mix-blend-multiply",
                isFocused ? "ring-2 ring-[var(--ring)] ring-offset-1" : "",
              ]
                .filter(Boolean)
                .join(" ")}
              style={{
                left: `${x0 * 100}%`,
                top: `${y0 * 100}%`,
                width: `${Math.max(0, x1 - x0) * 100}%`,
                height: `${Math.max(0, y1 - y0) * 100}%`,
                background: isUnderline
                  ? undefined
                  : colorWithOpacity(annotation.color, isFocused ? 0.85 : 0.6),
                borderBottom: isUnderline
                  ? `2px solid ${colorWithOpacity(annotation.color, 1)}`
                  : undefined,
                borderRadius: isUnderline ? 0 : 2,
              }}
            >
              <Tooltip label={label}>
                <button
                  type="button"
                  aria-label={label}
                  onClick={() => onAnnotationClick?.(annotation)}
                  className="block cursor-pointer"
                >
                  {annotation.author === "assistant" && index === 0 && (
                    <span
                      aria-hidden
                      className="absolute -top-1 -right-1 h-1.5 w-1.5 rounded-full bg-[var(--primary)] shadow-sm"
                    />
                  )}
                </button>
              </Tooltip>
            </span>
          );
        }),
      )}
      {(flashRects ?? []).map((rect, index) => {
        const [x0, y0, x1, y1] = rect;
        return (
          <span
            key={`flash-${index}`}
            aria-hidden
            className="dt-reader-flash absolute rounded-[2px]"
            style={{
              left: `${x0 * 100}%`,
              top: `${y0 * 100}%`,
              width: `${Math.max(0, x1 - x0) * 100}%`,
              height: `${Math.max(0, y1 - y0) * 100}%`,
            }}
          />
        );
      })}
    </div>
  );
}
