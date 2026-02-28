import { useState } from 'react'

interface AvatarProps {
  name: string
  imageUrl?: string | null
  size?: 'sm' | 'md' | 'lg'
  className?: string
}

const sizes = {
  sm: 'w-9 h-9 text-sm',
  md: 'w-8 h-8 text-sm',
  lg: 'w-14 h-14 text-2xl',
}

export default function Avatar({ name, imageUrl, size = 'md', className = '' }: AvatarProps) {
  const [imgFailed, setImgFailed] = useState(false)
  const sizeClass = sizes[size]
  const initial = (name || '?')[0].toUpperCase()

  if (imageUrl && !imgFailed) {
    return (
      <img
        src={imageUrl}
        alt={name}
        className={`${sizeClass} rounded-full flex-shrink-0 object-cover ${className}`}
        onError={() => setImgFailed(true)}
      />
    )
  }

  return (
    <div className={`${sizeClass} rounded-full flex-shrink-0 flex items-center justify-center font-bold text-white bg-gradient-to-br from-violet to-cyan ${className}`}>
      {initial}
    </div>
  )
}
