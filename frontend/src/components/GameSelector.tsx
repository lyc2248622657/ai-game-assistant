import type { GameInfo } from '../types'

interface Props {
  games: GameInfo[]
  current: GameInfo | null
  onSelect: (game: GameInfo) => void
}

/** 游戏选择器：切换游戏 = 切换知识包与独立会话 */
export function GameSelector({ games, current, onSelect }: Props) {
  return (
    <div className="flex items-center gap-2">
      <span className="text-sm text-gray-500">选择游戏</span>
      <div className="flex gap-2">
        {games.map((g) => (
          <button
            key={g.game_id}
            onClick={() => onSelect(g)}
            className={`rounded-lg px-4 py-2 text-sm font-medium transition ${
              current?.game_id === g.game_id
                ? 'bg-blue-600 text-white'
                : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
            }`}
          >
            {g.name}
          </button>
        ))}
      </div>
    </div>
  )
}
