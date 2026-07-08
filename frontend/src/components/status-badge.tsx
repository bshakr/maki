import { Badge } from "@/components/ui/badge";
import { HEALTH_PRESENTATION, type Health } from "@/lib/health";

// Calm status pill: outline "stable" for healthy, solid red "DEGRADED" for
// errors, solid amber "DEPLOYING" mid-rollout. Saturated color is reserved for
// problems; healthy stays quiet.
export function StatusBadge({ health }: { health: Health }) {
  if (health === "error") {
    return <Badge variant="destructive">DEGRADED</Badge>;
  }
  if (health === "deploying") {
    return (
      <Badge className="border-transparent bg-amber-500 text-white">
        DEPLOYING
      </Badge>
    );
  }
  return (
    <Badge variant="outline" className="text-muted-foreground">
      {HEALTH_PRESENTATION.healthy.word}
    </Badge>
  );
}
