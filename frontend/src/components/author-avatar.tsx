import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";

// First 1–2 initials from a name, uppercase. "?" when the name is missing.
function initialsOf(name: string | null): string {
  if (!name) return "?";
  const words = name.trim().split(/\s+/).filter(Boolean);
  if (words.length === 0) return "?";
  if (words.length === 1) return words[0].slice(0, 2).toUpperCase();
  return (words[0][0] + words[1][0]).toUpperCase();
}

export function AuthorAvatar({
  name,
  src,
  className,
}: {
  name: string | null;
  src: string | null;
  className?: string;
}) {
  // Nothing to show: no author and no avatar URL.
  if (!name && !src) return null;
  return (
    <Avatar size="sm" className={className}>
      {src && <AvatarImage src={src} alt={name ?? ""} />}
      <AvatarFallback>{initialsOf(name)}</AvatarFallback>
    </Avatar>
  );
}
