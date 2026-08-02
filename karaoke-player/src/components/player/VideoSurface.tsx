import { useEffect, useRef } from 'react'
import { coverUrl } from '../../api/media'
import { engine } from '../../player/PlaybackEngine'
import { usePlayerStore } from '../../stores/playerStore'

/** Hosts the engine-owned <video> element; styled fallback when the song has no MV. */
export function VideoSurface() {
  const song = usePlayerStore((s) => s.song)
  const containerRef = useRef<HTMLDivElement | null>(null)
  const hasVideo = !!song?.has_video

  useEffect(() => {
    const container = containerRef.current
    if (!container || !hasVideo) return
    engine.video.className = 'video-el'
    container.appendChild(engine.video)
    return () => {
      engine.video.remove()
    }
  }, [hasVideo, song?.id])

  return (
    <div className={`video-surface ${hasVideo ? '' : 'video-surface--fallback'}`} ref={containerRef}>
      {!hasVideo && song ? (
        <>
          {song.has_cover ? (
            <div
              className="video-fallback-cover"
              style={{ backgroundImage: `url(${coverUrl(song.id, song.updated_at)})` }}
            />
          ) : null}
          <div className="video-fallback">
            {song.has_cover ? (
              <img className="video-fallback-art" src={coverUrl(song.id, song.updated_at)} alt="" />
            ) : null}
            <div className="video-fallback-title">{song.title}</div>
            {song.artist ? <div className="video-fallback-artist">{song.artist}</div> : null}
          </div>
        </>
      ) : null}
    </div>
  )
}
