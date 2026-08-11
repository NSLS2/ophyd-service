import { TiledLookup } from '@blueskyproject/finch'

/**
 * TiledViewer page - displays scan data from the Tiled server using Finch's
 * TiledLookup component. This allows users to browse PD scan results and
 * other bluesky runs stored in the MongoDB catalog.
 */
export default function TiledViewer() {
  return (
    <div className="flex flex-col w-full h-full min-h-[600px]">
      <TiledLookup backgroundClassName="text-slate-700" />
    </div>
  )
}
