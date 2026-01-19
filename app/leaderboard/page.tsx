'use client'

import { useState, useEffect } from 'react'
import { getWalletBalance } from '@/lib/solana'
import Link from 'next/link'

interface Participant {
  address: string
  balance: number
  loading: boolean
}

interface Competition {
  name: string
  startingAmount: number
  targetAmount: number
  currency: string
  participants: string[]
}

export default function Leaderboard() {
  const [participants, setParticipants] = useState<Participant[]>([])
  const [competition, setCompetition] = useState<Competition | null>(null)

  useEffect(() => {
  const loadCompetition = async () => {
    const { supabase } = await import('@/lib/supabase')
    
    // Get the most recent competition
    const { data, error } = await supabase
      .from('competitions')
      .select('*')
      .order('created_at', { ascending: false })
      .limit(1)
      .single()
    
    if (error) {
      console.error('Error loading competition:', error)
      return
    }
    
    if (data) {
      const comp = {
        name: data.name,
        startingAmount: data.starting_amount,
        targetAmount: data.target_amount,
        currency: data.currency,
        participants: data.participants
      }
      
      setCompetition(comp)
      
      const initialParticipants = comp.participants.map((address: string) => ({
        address,
        balance: 0,
        loading: true
      }))
      setParticipants(initialParticipants)
      
      // Fetch balances
      comp.participants.forEach(async (address: string, index: number) => {
        try {
          const balance = await getWalletBalance(address)
          setParticipants(prev => {
            const updated = [...prev]
            updated[index] = { ...updated[index], balance, loading: false }
            return updated
          })
        } catch (error) {
          console.error('Error:', error)
          setParticipants(prev => {
            const updated = [...prev]
            updated[index] = { ...updated[index], loading: false }
            return updated
          })
        }
      })
    }
  }
  
  loadCompetition()
}, [])

  const sorted = [...participants].sort((a, b) => b.balance - a.balance)

  if (!competition) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-purple-900 via-blue-900 to-black p-8">
        <div className="max-w-4xl mx-auto text-center">
          <h1 className="text-4xl font-bold text-white mb-4">No Competition Yet</h1>
          <p className="text-gray-300 mb-8">Create a competition first!</p>
          <Link 
            href="/"
            className="bg-purple-600 text-white px-6 py-3 rounded-lg hover:bg-purple-700 inline-block"
          >
            Create Competition
          </Link>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-purple-900 via-blue-900 to-black p-8">
      <div className="max-w-4xl mx-auto">
        <Link href="/" className="text-purple-400 hover:text-purple-300 mb-4 inline-block">
          ← Back
        </Link>
        
        <h1 className="text-4xl font-bold text-white mb-2">🏆 {competition.name}</h1>
        <p className="text-gray-300 mb-8">
          {competition.startingAmount} → {competition.targetAmount} {competition.currency}
        </p>

        <div className="bg-white/10 backdrop-blur-lg rounded-2xl p-8 border border-white/20">
          {participants.length === 0 ? (
            <p className="text-gray-400 text-center">No participants</p>
          ) : (
            sorted.map((participant, index) => (
              <div key={participant.address} className="mb-4 bg-white/5 rounded-lg p-6">
                <div className="flex justify-between items-center">
                  <div>
                    <div className={`text-2xl font-bold ${
                      index === 0 ? 'text-yellow-400' : 
                      index === 1 ? 'text-gray-300' : 
                      index === 2 ? 'text-orange-400' : 
                      'text-gray-500'
                    }`}>
                      #{index + 1}
                    </div>
                    <div className="text-white font-mono text-sm mt-2">
                      {participant.address.slice(0, 8)}...{participant.address.slice(-8)}
                    </div>
                  </div>
                  
                  <div className="text-right">
                    {participant.loading ? (
                      <div className="text-gray-400 animate-pulse">Loading...</div>
                    ) : (
                      <div>
                        <div className="text-2xl font-bold text-white">
                          {participant.balance.toFixed(4)} {competition.currency}
                        </div>
                        <div className="text-sm text-gray-400">
                          {((participant.balance / competition.targetAmount) * 100).toFixed(1)}% to goal
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  )
}