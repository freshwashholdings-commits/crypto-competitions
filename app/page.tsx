'use client'

import { useState } from 'react'
import Link from 'next/link'

export default function Home() {
  const [competitionName, setCompetitionName] = useState('')
  const [startingAmount, setStartingAmount] = useState('1')
  const [targetAmount, setTargetAmount] = useState('100')
  const [currency, setCurrency] = useState('SOL')
  const [participants, setParticipants] = useState('')

const handleCreateCompetition = async (e: React.FormEvent) => {
  e.preventDefault()
  
  const competition = {
    name: competitionName,
    starting_amount: parseFloat(startingAmount),
    target_amount: parseFloat(targetAmount),
    currency,
    participants: participants.split('\n').filter(p => p.trim())
  }
  
  // Import supabase at the top of the function
  const { supabase } = await import('@/lib/supabase')
  
  // Save to Supabase
  const { data, error } = await supabase
    .from('competitions')
    .insert([competition])
    .select()
  
  if (error) {
    alert('Error creating competition: ' + error.message)
  } else {
    alert('Competition created! Go to the leaderboard to see it.')
    // Clear form
    setCompetitionName('')
    setParticipants('')
  }
}

  return (
    <div className="min-h-screen bg-gradient-to-br from-purple-900 via-blue-900 to-black p-8">
      <div className="max-w-2xl mx-auto">
        {/* Header */}
        <div className="text-center mb-12">
          <h1 className="text-5xl font-bold text-white mb-2">
            🚀 Crypto Competitions
          </h1>
          <p className="text-gray-300 text-lg">
            Track your memecoin trading competitions
          </p>
        </div>

        {/* View Leaderboard Button */}
        <div className="text-center mb-8">
          <Link 
            href="/leaderboard"
            className="inline-block bg-gradient-to-r from-yellow-500 to-orange-500 text-white font-bold py-3 px-8 rounded-lg hover:from-yellow-600 hover:to-orange-600 transform hover:scale-105 transition-all duration-200 shadow-lg"
          >
            🏆 View Leaderboard
          </Link>
        </div>

        {/* Create Competition Form */}

        {/* Create Competition Form */}
        <div className="bg-white/10 backdrop-blur-lg rounded-2xl p-8 shadow-2xl border border-white/20">
          <h2 className="text-2xl font-bold text-white mb-6">Create New Competition</h2>
          
          <form onSubmit={handleCreateCompetition} className="space-y-6">
            {/* Competition Name */}
            <div>
              <label className="block text-white mb-2 font-medium">
                Competition Name
              </label>
              <input
                type="text"
                value={competitionName}
                onChange={(e) => setCompetitionName(e.target.value)}
                placeholder="e.g., 1 to 100 SOL Challenge"
                className="w-full px-4 py-3 rounded-lg bg-white/10 border border-white/20 text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-purple-500"
                required
              />
            </div>

            {/* Currency Selection */}
            <div>
              <label className="block text-white mb-2 font-medium">
                Currency
              </label>
              <select
                value={currency}
                onChange={(e) => setCurrency(e.target.value)}
                className="w-full px-4 py-3 rounded-lg bg-white/10 border border-white/20 text-white focus:outline-none focus:ring-2 focus:ring-purple-500"
              >
                <option value="SOL">Solana (SOL)</option>
                <option value="USDC">USDC on Solana</option>
                <option value="BTC">Bitcoin (Coming Soon)</option>
                <option value="ETH">Ethereum (Coming Soon)</option>
              </select>
            </div>

            {/* Starting Amount */}
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-white mb-2 font-medium">
                  Starting Amount
                </label>
                <input
                  type="number"
                  step="0.01"
                  value={startingAmount}
                  onChange={(e) => setStartingAmount(e.target.value)}
                  className="w-full px-4 py-3 rounded-lg bg-white/10 border border-white/20 text-white focus:outline-none focus:ring-2 focus:ring-purple-500"
                  required
                />
              </div>

              {/* Target Amount */}
              <div>
                <label className="block text-white mb-2 font-medium">
                  Target Amount
                </label>
                <input
                  type="number"
                  step="0.01"
                  value={targetAmount}
                  onChange={(e) => setTargetAmount(e.target.value)}
                  className="w-full px-4 py-3 rounded-lg bg-white/10 border border-white/20 text-white focus:outline-none focus:ring-2 focus:ring-purple-500"
                  required
                />
              </div>
            </div>

            {/* Participant Wallets */}
            <div>
              <label className="block text-white mb-2 font-medium">
                Participant Wallet Addresses
              </label>
              <textarea
                value={participants}
                onChange={(e) => setParticipants(e.target.value)}
                placeholder={`Enter one Solana wallet address per line
Example:
7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU
9W6z3PXqvFqBLxqP3qR4KsR5G3jY8Ux7Vm2qTvYxJmHN`}
                rows={5}
                className="w-full px-4 py-3 rounded-lg bg-white/10 border border-white/20 text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-purple-500 font-mono text-sm"
                required
              />
              <p className="text-gray-400 text-sm mt-2">
                Enter Solana wallet addresses (one per line)
              </p>
            </div>

            {/* Submit Button */}
            <button
              type="submit"
              className="w-full bg-gradient-to-r from-purple-600 to-blue-600 text-white font-bold py-4 px-6 rounded-lg hover:from-purple-700 hover:to-blue-700 transform hover:scale-105 transition-all duration-200 shadow-lg"
            >
              Create Competition 🏆
            </button>
          </form>
        </div>

        {/* Info Section */}
        <div className="mt-8 text-center text-gray-400 text-sm">
          <p>💡 Tip: Wallet tracking is read-only and safe - no connection required!</p>
        </div>
      </div>
    </div>
  )
}