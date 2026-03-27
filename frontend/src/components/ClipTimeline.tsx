import { useState } from "react";
import {
  DndContext,
  closestCenter,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import {
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import {
  GripVertical,
  Trash2,
  Sparkles,
  Play,
  Loader2,
  AlertCircle,
  Music,
} from "lucide-react";
import clsx from "clsx";
import type { Clip } from "../utils/types";

interface ClipTimelineProps {
  clips: Clip[];
  onReorder: (clipIds: number[]) => void;
  onDelete: (clipId: number) => void;
  onUseSuggestion: (clipId: number) => void;
}

export default function ClipTimeline({
  clips,
  onReorder,
  onDelete,
  onUseSuggestion,
}: ClipTimelineProps) {
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 8 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates })
  );

  function handleDragEnd(event: DragEndEvent) {
    const { active, over } = event;
    if (!over || active.id === over.id) return;

    const oldIndex = clips.findIndex((c) => c.id === active.id);
    const newIndex = clips.findIndex((c) => c.id === over.id);

    const reordered = [...clips];
    const [moved] = reordered.splice(oldIndex, 1);
    reordered.splice(newIndex, 0, moved);

    onReorder(reordered.map((c) => c.id));
  }

  if (clips.length === 0) {
    return (
      <div className="py-16 text-center">
        <Music className="mx-auto mb-3 h-10 w-10 text-zinc-700" />
        <p className="text-zinc-500">No clips yet. Search and add songs to get started!</p>
      </div>
    );
  }

  return (
    <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleDragEnd}>
      <SortableContext items={clips.map((c) => c.id)} strategy={verticalListSortingStrategy}>
        <div className="space-y-2">
          {clips.map((clip, index) => (
            <SortableClipRow
              key={clip.id}
              clip={clip}
              index={index}
              onDelete={onDelete}
              onUseSuggestion={onUseSuggestion}
            />
          ))}
        </div>
      </SortableContext>
    </DndContext>
  );
}

function SortableClipRow({
  clip,
  index,
  onDelete,
  onUseSuggestion,
}: {
  clip: Clip;
  index: number;
  onDelete: (id: number) => void;
  onUseSuggestion: (id: number) => void;
}) {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: clip.id });

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
  };

  const statusConfig: Record<string, { color: string; icon: React.ReactNode; label: string }> = {
    pending: {
      color: "bg-zinc-600",
      icon: null,
      label: "Pending",
    },
    downloading: {
      color: "bg-blue-500 animate-pulse",
      icon: <Loader2 className="h-3.5 w-3.5 animate-spin text-blue-400" />,
      label: "Downloading...",
    },
    analyzing: {
      color: "bg-purple-500 animate-pulse",
      icon: <Loader2 className="h-3.5 w-3.5 animate-spin text-purple-400" />,
      label: "Analyzing audio...",
    },
    ready: {
      color: "bg-green-500",
      icon: null,
      label: "Ready",
    },
    error: {
      color: "bg-red-500",
      icon: <AlertCircle className="h-3.5 w-3.5 text-red-400" />,
      label: "Error",
    },
  };

  const status = statusConfig[clip.status] ?? statusConfig.pending;

  return (
    <div
      ref={setNodeRef}
      style={style}
      className={clsx(
        "card flex items-center gap-3",
        isDragging && "z-50 shadow-xl shadow-black/30 ring-1 ring-brand-500"
      )}
    >
      {/* Position */}
      <div className="flex w-7 shrink-0 items-center justify-center">
        <span className="font-mono text-xs text-zinc-600">{index + 1}</span>
      </div>

      {/* Drag handle */}
      <button
        {...attributes}
        {...listeners}
        className="shrink-0 cursor-grab touch-none rounded p-0.5 text-zinc-700 hover:text-zinc-400 active:cursor-grabbing"
      >
        <GripVertical className="h-4 w-4" />
      </button>

      {/* Thumbnail */}
      {clip.source_thumbnail ? (
        <img
          src={clip.source_thumbnail}
          alt={clip.source_title}
          className="h-12 w-20 shrink-0 rounded object-cover"
        />
      ) : (
        <div className="flex h-12 w-20 shrink-0 items-center justify-center rounded bg-zinc-800">
          <Play className="h-4 w-4 text-zinc-600" />
        </div>
      )}

      {/* Info */}
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium text-zinc-200">
          {clip.source_title || "Untitled"}
        </p>
        <div className="flex items-center gap-2 text-xs text-zinc-500">
          <span>{clip.source_artist}</span>
          {clip.bpm && <span>· {Math.round(clip.bpm)} BPM</span>}
          {clip.status === "ready" && (
            <span>
              · {fmtTime(clip.start_time)} → {fmtTime(clip.end_time)}
            </span>
          )}
          {status.icon}
          {clip.status !== "ready" && (
            <span className="text-zinc-600">{status.label}</span>
          )}
        </div>
      </div>

      {/* Status dot */}
      <div className={clsx("h-2 w-2 shrink-0 rounded-full", status.color)} />

      {/* Actions */}
      <div className="flex shrink-0 items-center gap-1">
        {clip.suggested_start !== null && clip.status === "ready" && (
          <button
            onClick={() => onUseSuggestion(clip.id)}
            className="rounded p-1.5 text-zinc-500 transition-colors hover:bg-zinc-800 hover:text-purple-400"
            title="Use AI-suggested best segment"
          >
            <Sparkles className="h-4 w-4" />
          </button>
        )}
        <button
          onClick={() => onDelete(clip.id)}
          className="rounded p-1.5 text-zinc-600 transition-colors hover:bg-zinc-800 hover:text-red-400"
        >
          <Trash2 className="h-4 w-4" />
        </button>
      </div>
    </div>
  );
}

function fmtTime(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}
