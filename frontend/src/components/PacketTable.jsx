import React, { useState, useMemo } from 'react';

const PROTOCOL_BADGES = {
  TCP: 'bg-indigo-500/15 text-indigo-400 border-indigo-500/30',
  UDP: 'bg-cyan-500/15 text-cyan-400 border-cyan-500/30',
  ICMP: 'bg-amber-500/15 text-amber-400 border-amber-500/30',
  ARP: 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30',
  DEFAULT: 'bg-slate-700/30 text-slate-300 border-slate-600/40',
};

/**
 * PacketTable — displays real-time packet stream with live filter & search.
 */
export default function PacketTable({ packets = [], isCapturing }) {
  const [filter, setFilter] = useState('');
  const [protocolFilter, setProtocolFilter] = useState('ALL');

  const filteredPackets = useMemo(() => {
    let list = [...packets].reverse(); // newest first

    if (protocolFilter !== 'ALL') {
      list = list.filter((p) => p.protocol.toUpperCase() === protocolFilter);
    }

    if (filter.trim()) {
      const q = filter.trim().toLowerCase();
      list = list.filter(
        (p) =>
          p.src_ip.toLowerCase().includes(q) ||
          p.dst_ip.toLowerCase().includes(q) ||
          p.protocol.toLowerCase().includes(q) ||
          (p.info && p.info.toLowerCase().includes(q))
      );
    }

    return list;
  }, [packets, filter, protocolFilter]);

  const protocolsPresent = useMemo(() => {
    const set = new Set();
    packets.forEach((p) => set.add(p.protocol.toUpperCase()));
    return ['ALL', ...Array.from(set)];
  }, [packets]);

  return (
    <div className="glass-panel rounded-2xl overflow-hidden flex flex-col" id="recent-packets-table">
      {/* Table Header Controls */}
      <div className="p-4 sm:p-5 border-b border-slate-800/80 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <h3 className="text-sm font-semibold tracking-wide text-white uppercase flex items-center gap-2">
            Recent Packet Feed
            <span className="text-xs font-mono font-normal px-2 py-0.5 rounded-full bg-slate-800 text-slate-400">
              {filteredPackets.length} {filteredPackets.length === 1 ? 'packet' : 'packets'}
            </span>
          </h3>
        </div>

        {/* Search & Filter */}
        <div className="flex flex-wrap items-center gap-2">
          {/* Protocol dropdown */}
          <select
            value={protocolFilter}
            onChange={(e) => setProtocolFilter(e.target.value)}
            className="text-xs bg-slate-900 border border-slate-700 rounded-lg px-2.5 py-1.5 text-slate-300 focus:outline-none focus:border-indigo-500"
          >
            {protocolsPresent.map((proto) => (
              <option key={proto} value={proto}>
                {proto === 'ALL' ? 'All Protocols' : proto}
              </option>
            ))}
          </select>

          {/* Text filter */}
          <div className="relative">
            <input
              type="text"
              placeholder="Search IP, port, info..."
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              className="text-xs bg-slate-900 border border-slate-700 rounded-lg pl-8 pr-3 py-1.5 text-slate-200 placeholder-slate-500 focus:outline-none focus:border-indigo-500 w-44 sm:w-56"
            />
            <svg
              className="w-3.5 h-3.5 text-slate-500 absolute left-2.5 top-1/2 -translate-y-1/2"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
            </svg>
          </div>
        </div>
      </div>

      {/* Table Content */}
      <div className="overflow-x-auto max-h-[380px] overflow-y-auto">
        {filteredPackets.length === 0 ? (
          <div className="py-16 text-center text-slate-500">
            <svg
              className="w-10 h-10 mx-auto mb-2 text-slate-600"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.5" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
            </svg>
            <p className="text-sm font-medium">No packets matching criteria</p>
            <p className="text-xs text-slate-600 mt-1">
              {isCapturing ? 'Listening for live packet metadata...' : 'Start a capture session to stream network traffic'}
            </p>
          </div>
        ) : (
          <table className="w-full text-left border-collapse text-xs">
            <thead className="bg-slate-900/90 text-slate-400 uppercase font-semibold text-[10px] tracking-wider sticky top-0 z-10 border-b border-slate-800">
              <tr>
                <th className="py-2.5 px-4">Time</th>
                <th className="py-2.5 px-4">Protocol</th>
                <th className="py-2.5 px-4">Source IP</th>
                <th className="py-2.5 px-4">Destination IP</th>
                <th className="py-2.5 px-4 text-right">Length</th>
                <th className="py-2.5 px-4">Details</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60 font-mono">
              {filteredPackets.map((pkt, idx) => {
                const protoBadge =
                  PROTOCOL_BADGES[pkt.protocol.toUpperCase()] || PROTOCOL_BADGES.DEFAULT;
                const dateStr = new Date(pkt.timestamp * 1000).toLocaleTimeString([], {
                  hour: '2-digit',
                  minute: '2-digit',
                  second: '2-digit',
                  fractionalSecondDigits: 3,
                });

                return (
                  <tr
                    key={`${pkt.timestamp}-${idx}`}
                    className="hover:bg-slate-800/40 transition-colors"
                  >
                    <td className="py-2 px-4 text-slate-400 whitespace-nowrap">{dateStr}</td>
                    <td className="py-2 px-4 whitespace-nowrap">
                      <span className={`px-2 py-0.5 rounded text-[10px] font-bold border ${protoBadge}`}>
                        {pkt.protocol}
                      </span>
                    </td>
                    <td className="py-2 px-4 text-indigo-300 font-medium whitespace-nowrap">
                      {pkt.src_ip}
                    </td>
                    <td className="py-2 px-4 text-cyan-300 font-medium whitespace-nowrap">
                      {pkt.dst_ip}
                    </td>
                    <td className="py-2 px-4 text-slate-300 text-right whitespace-nowrap">
                      {pkt.length} <span className="text-slate-500 text-[10px]">B</span>
                    </td>
                    <td className="py-2 px-4 text-slate-400 font-sans text-xs truncate max-w-xs" title={pkt.info}>
                      {pkt.info || '-'}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
