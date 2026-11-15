// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/// @title FollowRegistry
/// @notice SealCall follow registry (skeleton, phase 1).
///         Users follow an agent address; follows are zero-value,
///         non-custodial on-chain records used as the traction signal
///         for the SealCall dashboard. No funds are ever held here.
/// @dev    NOT audited. NOT deployed. Skeleton for the Base Builder Quest
///         (Stocks Maxxing Season); deployment is a separate, gated step.
contract FollowRegistry {
    mapping(address => mapping(address => bool)) private _following; // agent => follower => bool
    mapping(address => uint256) private _followerCount;               // agent => count

    event Followed(address indexed agent, address indexed follower, uint256 newFollowerCount);
    event Unfollowed(address indexed agent, address indexed follower, uint256 newFollowerCount);

    error AlreadyFollowing(address agent, address follower);
    error NotFollowing(address agent, address follower);
    error SelfFollow();

    /// @notice Follow an agent. One follow per (agent, follower) pair.
    function follow(address agent) external {
        if (agent == msg.sender) revert SelfFollow();
        if (_following[agent][msg.sender]) revert AlreadyFollowing(agent, msg.sender);
        _following[agent][msg.sender] = true;
        uint256 count = ++_followerCount[agent];
        emit Followed(agent, msg.sender, count);
    }

    /// @notice Stop following an agent.
    function unfollow(address agent) external {
        if (!_following[agent][msg.sender]) revert NotFollowing(agent, msg.sender);
        _following[agent][msg.sender] = false;
        uint256 count = --_followerCount[agent];
        emit Unfollowed(agent, msg.sender, count);
    }

    /// @notice Whether `follower` currently follows `agent`.
    function isFollowing(address agent, address follower) external view returns (bool) {
        return _following[agent][follower];
    }

    /// @notice Current follower count for an agent.
    function followerCount(address agent) external view returns (uint256) {
        return _followerCount[agent];
    }
}
