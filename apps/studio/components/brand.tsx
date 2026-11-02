import Image from "next/image";

export function Brand({ subtitle }: { subtitle: string }) {
  return (
    <div className="brand">
      <div className="brand-heading">
        <Image
          className="brand-logo brand-logo-light"
          src="/brand/foundry-magenta.png"
          alt=""
          width={56}
          height={56}
          unoptimized
        />
        <Image
          className="brand-logo brand-logo-dark"
          src="/brand/foundry-black.png"
          alt=""
          width={56}
          height={56}
          unoptimized
        />
        FOUNDRY
      </div>
      <span>{subtitle}</span>
    </div>
  );
}
