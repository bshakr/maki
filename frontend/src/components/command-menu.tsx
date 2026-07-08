import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";

import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import { fetchServices } from "@/api";
import { shortSha } from "@/lib/format";

interface CommandMenuProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function CommandMenu({ open, onOpenChange }: CommandMenuProps) {
  const navigate = useNavigate();
  const { data, isLoading, error } = useQuery({
    queryKey: ["services"],
    queryFn: () => fetchServices(),
    enabled: open,
  });
  const services = data?.services ?? null;

  function handleSelect(name: string) {
    onOpenChange(false);
    navigate(`/services/${name}`);
  }

  return (
    <CommandDialog
      open={open}
      onOpenChange={onOpenChange}
      title="Search services"
      description="Search deployed services and jump to one."
    >
      <CommandInput placeholder="Search services…" />
      <CommandList>
        {isLoading && services === null ? (
          <CommandEmpty>Loading services…</CommandEmpty>
        ) : error ? (
          <CommandEmpty>
            {error instanceof Error ? error.message : "Failed to load services"}
          </CommandEmpty>
        ) : (
          <>
            <CommandEmpty>No services found.</CommandEmpty>
            <CommandGroup heading="Services">
              {(services ?? []).map((svc) => (
                <CommandItem
                  key={svc.name}
                  value={svc.name}
                  onSelect={() => handleSelect(svc.name)}
                >
                  <span className="font-medium">{svc.name}</span>
                  <span className="ml-auto text-xs text-muted-foreground">
                    {svc.platform} · {shortSha(svc.git_sha)}
                  </span>
                </CommandItem>
              ))}
            </CommandGroup>
          </>
        )}
      </CommandList>
    </CommandDialog>
  );
}
