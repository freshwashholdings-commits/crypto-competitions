import { Connection, PublicKey, ParsedTransactionWithMeta } from '@solana/web3.js'

// Free public RPC endpoint
const SOLANA_RPC = 'https://mainnet.helius-rpc.com/?api-key=de0d0113-b0ba-403b-9ef2-f52e01da9593'
const connection = new Connection(SOLANA_RPC, 'confirmed')

export interface WalletStats {
  address: string
  currentBalance: number
  totalTrades: number
  wins: number
  losses: number
  winRate: number
  totalProfitLoss: number
}

// Get SOL balance for a wallet
export async function getWalletBalance(address: string): Promise<number> {
  try {
    const publicKey = new PublicKey(address)
    const balance = await connection.getBalance(publicKey)
    return balance / 1e9
  } catch (error) {
    console.error('Error fetching balance:', error)
    return 0
  }
}

// Get recent transactions for a wallet
export async function getWalletTransactions(
  address: string,
  limit: number = 10
): Promise<ParsedTransactionWithMeta[]> {
  try {
    const publicKey = new PublicKey(address)
    const signatures = await connection.getSignaturesForAddress(publicKey, { limit })
    
    const transactions: ParsedTransactionWithMeta[] = []
    
    for (const sig of signatures) {
      const tx = await connection.getParsedTransaction(sig.signature, {
        maxSupportedTransactionVersion: 0
      })
      if (tx) {
        transactions.push(tx)
      }
    }
    
    return transactions
  } catch (error) {
    console.error('Error fetching transactions:', error)
    return []
  }
}

// Calculate basic wallet stats
export async function getWalletStats(address: string): Promise<WalletStats> {
  const balance = await getWalletBalance(address)
  const transactions = await getWalletTransactions(address, 50)
  
  return {
    address,
    currentBalance: balance,
    totalTrades: transactions.length,
    wins: 0,
    losses: 0,
    winRate: 0,
    totalProfitLoss: 0
  }
}