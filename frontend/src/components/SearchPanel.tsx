import { useState } from "react";
import { Search, Download, Loader2, ExternalLink } from "lucide-react";
import type { SearchResult } from "../utils/types";
import { searchYouTube } from "../utils/api";

interface SearchPanelProps {
  onAddClip: (result: SearchResult) => void;
  addedIds: Set<string>;
}

export default function SearchPanel({ onAddClip, addedIds }: SearchPanelProps) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [searching, setSearching] = useState(false);
  const [error, setError] = useState("");

  async function handleSearch(e: React.FormEvent) {
    e.preventDefault();
    if (!query.trim()) return;

    setSearching(true);
    setError("");
    try {
      const data = await searchYouTube(query);
      setResults(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Search failed");
    } finally {
      setSearching(false);
    }
  }

  return (
    <div>
      <form onSubmit={handleSearch} className="mb-4 flex gap-2">
        <input
          type="text"
          className="input-field"
          placeholder='Search for music videos... (e.g. "Bohemian Rhapsody")'
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <button type="submit" disabled={searching} className="btn-primary shrink-0">
          {searching ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Search className="h-4 w-4" />
          )}
          Search
        </button>
      </form>

      {error && (
        <div className="mb-4 rounded-lg border border-red-900 bg-red-950 px-4 py-2 text-sm text-red-300">
          {error}
        </div>
      )}

      <div className="space-y-2">
        {results.map((result) => {
          const alreadyAdded = addedIds.has(result.youtube_id);

          return (
            <div
              key={result.youtube_id}
              className="card flex items-center gap-4 transition-opacity"
              style={{ opacity: alreadyAdded ? 0.5 : 1 }}
            >
              {/* Thumbnail */}
              <div className="relative shrink-0">
                <img
                  src={result.thumbnail}
                  alt={result.title}
                  className="h-16 w-28 rounded object-cover"
                />
                {result.duration && (
                  <span className="absolute bottom-1 right-1 rounded bg-black/80 px-1 py-0.5 text-[10px] font-mono text-white">
                    {result.duration}
                  </span>
                )}
              </div>

              {/* Info */}
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium text-zinc-100">
                  {result.title}
                </p>
                <p className="text-xs text-zinc-500">{result.artist}</p>
                {result.view_count && (
                  <p className="text-xs text-zinc-600">
                    {Number(result.view_count).toLocaleString()} views
                  </p>
                )}
              </div>

              {/* Actions */}
              <div className="flex shrink-0 items-center gap-1.5">
                <a
                  href={`https://www.youtube.com/watch?v=${result.youtube_id}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="rounded p-1.5 text-zinc-600 transition-colors hover:bg-zinc-800 hover:text-zinc-300"
                  title="Preview on YouTube"
                >
                  <ExternalLink className="h-4 w-4" />
                </a>
                <button
                  onClick={() => onAddClip(result)}
                  disabled={alreadyAdded}
                  className="btn-primary text-xs"
                >
                  <Download className="h-3.5 w-3.5" />
                  {alreadyAdded ? "Added" : "Add"}
                </button>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
