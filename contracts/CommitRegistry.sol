// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/// @title CommitRegistry
/// @notice SealCall decision sealing registry (skeleton, phase 1).
///         An agent first commits keccak256(decision || salt) on-chain,
///         then reveals the decision after `revealTime`. Anyone can later
///         verify that the revealed decision matches the sealed hash and
///         that it was sealed before the reveal window opened — the
///         tamper-evident track record at the heart of SealCall.
/// @dev    NOT audited. NOT deployed. Skeleton for the Base Builder Quest
///         (Stocks Maxxing Season); deployment is a separate, gated step.
contract CommitRegistry {
    struct Commitment {
        address agent;          // who sealed the decision
        bytes32 commitmentHash; // keccak256(abi.encodePacked(decision, salt))
        uint64 committedAt;     // block timestamp of the commit
        uint64 revealTime;      // earliest timestamp at which reveal is allowed
        bool revealed;
        bytes32 decisionHash;   // keccak256(decision), set at reveal time
    }

    Commitment[] private _commitments;

    event Committed(
        uint256 indexed id,
        address indexed agent,
        bytes32 commitmentHash,
        uint64 revealTime
    );
    event Revealed(uint256 indexed id, address indexed agent, bytes32 decisionHash);

    error UnknownCommitment(uint256 id);
    error NotCommitter(uint256 id, address caller);
    error AlreadyRevealed(uint256 id);
    error RevealTooEarly(uint256 id, uint64 revealTime);
    error HashMismatch(uint256 id);

    /// @notice Seal a decision. `commitmentHash` must equal
    ///         keccak256(abi.encodePacked(decision, salt)) for the reveal
    ///         to succeed later. The decision itself stays off-chain
    ///         (and secret) until reveal.
    /// @param commitmentHash Hash of the decision payload plus a secret salt.
    /// @param revealTime Earliest unix timestamp at which reveal is allowed.
    /// @return id Index of the stored commitment.
    function commit(bytes32 commitmentHash, uint64 revealTime)
        external
        returns (uint256 id)
    {
        id = _commitments.length;
        _commitments.push(
            Commitment({
                agent: msg.sender,
                commitmentHash: commitmentHash,
                committedAt: uint64(block.timestamp),
                revealTime: revealTime,
                revealed: false,
                decisionHash: bytes32(0)
            })
        );
        emit Committed(id, msg.sender, commitmentHash, revealTime);
    }

    /// @notice Reveal a previously sealed decision.
    /// @param id Commitment index returned by `commit`.
    /// @param decision The full decision payload that was sealed.
    /// @param salt The secret salt used when sealing.
    function reveal(uint256 id, bytes calldata decision, bytes32 salt) external {
        if (id >= _commitments.length) revert UnknownCommitment(id);
        Commitment storage c = _commitments[id];
        if (c.agent != msg.sender) revert NotCommitter(id, msg.sender);
        if (c.revealed) revert AlreadyRevealed(id);
        if (block.timestamp < c.revealTime) revert RevealTooEarly(id, c.revealTime);
        bytes32 check = keccak256(abi.encodePacked(decision, salt));
        if (check != c.commitmentHash) revert HashMismatch(id);
        c.revealed = true;
        c.decisionHash = keccak256(decision);
        emit Revealed(id, msg.sender, c.decisionHash);
    }

    /// @notice Read one commitment back.
    function getCommitment(uint256 id) external view returns (Commitment memory) {
        if (id >= _commitments.length) revert UnknownCommitment(id);
        return _commitments[id];
    }

    /// @notice Total number of commitments ever sealed.
    function commitmentCount() external view returns (uint256) {
        return _commitments.length;
    }
}
