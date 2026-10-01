import type { SVGProps } from 'react'

type IconProps = Omit<SVGProps<SVGSVGElement>, 'viewBox' | 'fill'> & { size?: number }

function Base({ size = 18, children, ...rest }: IconProps & { children: React.ReactNode }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.75}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      {...rest}
    >
      {children}
    </svg>
  )
}

export const HomeIcon = (props: IconProps) => (
  <Base {...props}>
    <path d="M4 11.5 12 4l8 7.5" />
    <path d="M6 10v9a1 1 0 0 0 1 1h4v-6h2v6h4a1 1 0 0 0 1-1v-9" />
  </Base>
)

export const PlusIcon = (props: IconProps) => (
  <Base {...props}>
    <path d="M12 5v14M5 12h14" />
  </Base>
)

export const EditIcon = (props: IconProps) => (
  <Base {...props}>
    <path d="M4 20h4l10.5-10.5a2.1 2.1 0 0 0-3-3L5 17v3Z" />
  </Base>
)

export const CheckIcon = (props: IconProps) => (
  <Base {...props}>
    <path d="m5 13 4.5 4.5L19 8" />
  </Base>
)

export const ListIcon = (props: IconProps) => (
  <Base {...props}>
    <path d="M9 7h11M9 12h11M9 17h11" />
    <path d="M4 7h.01M4 12h.01M4 17h.01" />
  </Base>
)

export const BuildingIcon = (props: IconProps) => (
  <Base {...props}>
    <rect x="5" y="3" width="14" height="18" rx="1" />
    <path d="M9 8h1M14 8h1M9 12h1M14 12h1M9 16h1M14 16h1" />
    <path d="M10 21v-3h4v3" />
  </Base>
)

export const ArrowLeftIcon = (props: IconProps) => (
  <Base {...props}>
    <path d="M19 12H5M11 6l-6 6 6 6" />
  </Base>
)

export const ArrowRightIcon = (props: IconProps) => (
  <Base {...props}>
    <path d="M5 12h14M13 6l6 6-6 6" />
  </Base>
)

export const RefreshIcon = (props: IconProps) => (
  <Base {...props}>
    <path d="M20 11A8 8 0 0 0 6 6.3L4 8M4 13a8 8 0 0 0 14 4.7l2-1.7" />
    <path d="M4 4v4h4M20 20v-4h-4" />
  </Base>
)

export const UsersIcon = (props: IconProps) => (
  <Base {...props}>
    <circle cx="9" cy="8" r="3" />
    <path d="M3 20c0-3.3 2.7-6 6-6s6 2.7 6 6" />
    <path d="M16 4.2a3 3 0 0 1 0 5.8M21 20c0-2.8-1.9-5.1-4.5-5.8" />
  </Base>
)

export const AlertIcon = (props: IconProps) => (
  <Base {...props}>
    <path d="M12 3 2 20h20L12 3Z" />
    <path d="M12 10v4M12 17h.01" />
  </Base>
)

export const ChevronDownIcon = (props: IconProps) => (
  <Base {...props}>
    <path d="m6 9 6 6 6-6" />
  </Base>
)

export const CloseIcon = (props: IconProps) => (
  <Base {...props}>
    <path d="M6 6l12 12M18 6 6 18" />
  </Base>
)
