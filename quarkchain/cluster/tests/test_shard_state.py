import unittest
from quarkchain.cluster.tests.test_utils import get_test_env, create_transfer_transaction
from quarkchain.cluster.shard_state import ShardState
from quarkchain.core import Identity, Address
from quarkchain.evm import opcodes
from quarkchain.cluster.core import CrossShardTransactionDeposit, CrossShardTransactionList


def create_default_shard_state(env, shardId=0):
    return ShardState(
        env=env,
        shardId=shardId,
        createGenesis=True)


class TestShardState(unittest.TestCase):

    def testShardStateSimple(self):
        env = get_test_env()
        state = create_default_shard_state(env)
        self.assertEqual(state.rootTip.height, 0)
        self.assertEqual(state.headerTip.height, 0)

    def testOneTx(self):
        id1 = Identity.createRandomIdentity()
        acc1 = Address.createFromIdentity(id1)
        acc2 = Address.createRandomAccount()
        acc3 = Address.createRandomAccount(fullShardId=0)

        env = get_test_env(
            genesisAccount=acc1,
            genesisMinorQuarkash=10000000)
        state = create_default_shard_state(env=env)

        state.addTx(create_transfer_transaction(
            shardState=state,
            fromId=id1,
            toAddress=acc2,
            amount=12345))
        b1 = state.createBlockToMine(address=acc3)
        self.assertEqual(len(b1.txList), 1)

        # Should succeed
        state.finalizeAndAddBlock(b1)
        self.assertEqual(state.headerTip, b1.header)
        self.assertEqual(state.getBalance(id1.recipient), 10000000 - opcodes.GTXCOST - 12345)
        self.assertEqual(state.getBalance(acc2.recipient), 12345)
        self.assertEqual(state.getBalance(acc3.recipient), opcodes.GTXCOST // 2)

    def testTwoTx(self):
        id1 = Identity.createRandomIdentity()
        id2 = Identity.createRandomIdentity()
        acc1 = Address.createFromIdentity(id1)
        acc2 = Address.createFromIdentity(id2)
        acc3 = Address.createRandomAccount(fullShardId=0)

        env = get_test_env(
            genesisAccount=acc1,
            genesisMinorQuarkash=10000000)
        state = create_default_shard_state(env=env)

        state.addTx(create_transfer_transaction(
            shardState=state,
            fromId=id1,
            toAddress=acc2,
            amount=1234500))
        state.addTx(create_transfer_transaction(
            shardState=state,
            fromId=id2,
            toAddress=acc1,
            amount=234500))
        b1 = state.createBlockToMine(address=acc3)
        self.assertEqual(len(b1.txList), 2)

        # Should succeed
        state.finalizeAndAddBlock(b1)
        self.assertEqual(state.headerTip, b1.header)
        self.assertEqual(state.getBalance(id1.recipient), 10000000 - opcodes.GTXCOST - 1234500 + 234500)
        self.assertEqual(state.getBalance(acc2.recipient), 1234500 - 234500 - opcodes.GTXCOST)
        self.assertEqual(state.getBalance(acc3.recipient), opcodes.GTXCOST)

    def testXshardTxSent(self):
        id1 = Identity.createRandomIdentity()
        acc1 = Address.createFromIdentity(id1, fullShardId=1)
        acc2 = Address.createRandomAccount()
        acc3 = Address.createRandomAccount(fullShardId=0)

        env = get_test_env(
            genesisAccount=acc1,
            genesisMinorQuarkash=10000000)
        state = create_default_shard_state(env=env, shardId=0)

        state.addTx(create_transfer_transaction(
            shardState=state,
            fromId=id1,
            toAddress=acc2,
            amount=0,
            startgas=opcodes.GTXXSHARDCOST + opcodes.GTXCOST,
            withdraw=888888,
            withdrawTo=bytes(acc1.serialize())))

        b1 = state.createBlockToMine(address=acc3)
        self.assertEqual(len(b1.txList), 1)

        # Should succeed
        state.finalizeAndAddBlock(b1)
        self.assertEqual(len(state.evmState.xshard_list), 1)
        self.assertEqual(
            state.evmState.xshard_list[0],
            CrossShardTransactionDeposit(
                address=acc1,
                amount=888888,
                gasPrice=1))
        self.assertEqual(state.getBalance(id1.recipient), 10000000 - 888888 - opcodes.GTXCOST - opcodes.GTXXSHARDCOST)
        # Make sure the xshard gas is not used by local block
        self.assertEqual(state.evmState.gas_used, opcodes.GTXCOST)
        # GTXXSHARDCOST is consumed by remote shard
        self.assertEqual(state.getBalance(acc3.recipient), opcodes.GTXCOST // 2)

    def testAddBlockXshardTxSentWithIncorrectShardId(self):
        id1 = Identity.createRandomIdentity()
        acc1 = Address.createFromIdentity(id1, fullShardId=0)   # wrong full shard id
        acc2 = Address.createRandomAccount()

        env = get_test_env(
            genesisAccount=acc1,
            genesisMinorQuarkash=10000000)
        state = create_default_shard_state(env=env, shardId=0)

        b1 = state.getTip().createBlockToAppend()
        b1.addTx(create_transfer_transaction(
            shardState=state,
            fromId=id1,
            toAddress=acc2,
            amount=0,
            startgas=opcodes.GTXXSHARDCOST + opcodes.GTXCOST,
            withdraw=888888,
            withdrawTo=bytes(acc1.serialize())))

        with self.assertRaises(ValueError):
            state.runBlock(b1)

    def testCreateBlockToMineXshardTxSentWithIncorrectShardId(self):
        id1 = Identity.createRandomIdentity()
        acc1 = Address.createFromIdentity(id1, fullShardId=0)   # wrong full shard id
        acc2 = Address.createRandomAccount()

        env = get_test_env(
            genesisAccount=acc1,
            genesisMinorQuarkash=10000000)
        state = create_default_shard_state(env=env, shardId=0)

        state.addTx(create_transfer_transaction(
            shardState=state,
            fromId=id1,
            toAddress=acc2,
            amount=0,
            startgas=opcodes.GTXXSHARDCOST + opcodes.GTXCOST,
            withdraw=888888,
            withdrawTo=bytes(acc1.serialize())))
        b1 = state.createBlockToMine(address=acc1)
        self.assertEqual(len(b1.txList), 0)
        self.assertEqual(len(state.txQueue), 0)

    def testXshardTxReceived(self):
        id1 = Identity.createRandomIdentity()
        acc1 = Address.createFromIdentity(id1, fullShardId=0)
        acc2 = Address.createRandomAccount()
        acc3 = Address.createRandomAccount(fullShardId=0)

        env = get_test_env(
            genesisAccount=acc1,
            genesisMinorQuarkash=10000000)
        state0 = create_default_shard_state(env=env, shardId=0)
        state1 = create_default_shard_state(env=env, shardId=1)

        # Add one block in shard 0
        b0 = state0.createBlockToMine()
        state0.finalizeAndAddBlock(b0)

        b1 = state1.getTip().createBlockToAppend()
        evmTx = create_transfer_transaction(
            shardState=state1,
            fromId=id1,
            toAddress=acc2,
            amount=0,
            startgas=opcodes.GTXXSHARDCOST + opcodes.GTXCOST,
            gasPrice=2,
            withdraw=888888,
            withdrawTo=bytes(acc1.serialize()))
        b1.addTx(evmTx)

        # Add a x-shard tx from remote peer
        state0.addCrossShardTxListByMinorBlockHash(
            h=b1.header.getHash(),
            txList=CrossShardTransactionList(txList=[
                CrossShardTransactionDeposit(
                    address=acc1,
                    amount=888888,
                    gasPrice=2)
            ]))

        # Create a root block containing the block with the x-shard tx
        rB = state0.rootTip.createBlockToAppend() \
            .addMinorBlockHeader(b0.header) \
            .addMinorBlockHeader(b1.header) \
            .finalize()
        state0.addRootBlock(rB)

        # Add b0 and make sure all x-shard tx's are added
        b2 = state0.createBlockToMine(address=acc3)
        state0.finalizeAndAddBlock(b2)

        self.assertEqual(state0.getBalance(acc1.recipient), 10000000 + 888888)
        self.assertEqual(state0.getBalance(acc3.recipient), opcodes.GTXXSHARDCOST * 2 // 2)

    def testForkResolve(self):
        id1 = Identity.createRandomIdentity()
        acc1 = Address.createFromIdentity(id1, fullShardId=0)

        env = get_test_env(
            genesisAccount=acc1,
            genesisMinorQuarkash=10000000)
        state = create_default_shard_state(env=env, shardId=0)

        b0 = state.getTip().createBlockToAppend()
        b1 = state.getTip().createBlockToAppend()

        state.finalizeAndAddBlock(b0)
        self.assertEqual(state.headerTip, b0.header)

        # Fork happens, first come first serve
        state.finalizeAndAddBlock(b1)
        self.assertEqual(state.headerTip, b0.header)

        # Longer fork happens, override existing one
        b2 = b1.createBlockToAppend()
        state.finalizeAndAddBlock(b2)
        self.assertEqual(state.headerTip, b2.header)

    def testRootChainFirstConsensus(self):
        id1 = Identity.createRandomIdentity()
        acc1 = Address.createFromIdentity(id1, fullShardId=0)

        env = get_test_env(
            genesisAccount=acc1,
            genesisMinorQuarkash=10000000)
        state0 = create_default_shard_state(env=env, shardId=0)
        state1 = create_default_shard_state(env=env, shardId=1)

        # Add one block and prepare a fork
        b0 = state0.getTip().createBlockToAppend(address=acc1)
        b2 = state0.getTip().createBlockToAppend(address=Address.createEmptyAccount())

        state0.finalizeAndAddBlock(b0)
        state0.finalizeAndAddBlock(b2)

        b1 = state1.getTip().createBlockToAppend()
        b1.finalize(evmState=state1.runBlock(b1))

        # Create a root block containing the block with the x-shard tx
        state0.addCrossShardTxListByMinorBlockHash(
            h=b1.header.getHash(),
            txList=CrossShardTransactionList(txList=[]))
        rB = state0.rootTip.createBlockToAppend() \
            .addMinorBlockHeader(b0.header) \
            .addMinorBlockHeader(b1.header) \
            .finalize()
        state0.addRootBlock(rB)

        b00 = b0.createBlockToAppend()
        state0.finalizeAndAddBlock(b00)
        self.assertEqual(state0.headerTip, b00.header)

        # Create another fork that is much longer (however not confirmed by rB)
        b3 = b2.createBlockToAppend()
        state0.finalizeAndAddBlock(b3)
        b4 = b3.createBlockToAppend()
        state0.finalizeAndAddBlock(b4)
        self.assertGreater(b4.header.height, b00.header.height)
        self.assertEqual(state0.headerTip, b00.header)

    def testShardStateAddRootBlock(self):
        id1 = Identity.createRandomIdentity()
        acc1 = Address.createFromIdentity(id1, fullShardId=0)

        env = get_test_env(
            genesisAccount=acc1,
            genesisMinorQuarkash=10000000)
        state0 = create_default_shard_state(env=env, shardId=0)
        state1 = create_default_shard_state(env=env, shardId=1)

        # Add one block and prepare a fork
        b0 = state0.getTip().createBlockToAppend(address=acc1)
        b2 = state0.getTip().createBlockToAppend(address=Address.createEmptyAccount())

        state0.finalizeAndAddBlock(b0)
        state0.finalizeAndAddBlock(b2)

        b1 = state1.getTip().createBlockToAppend()
        b1.finalize(evmState=state1.runBlock(b1))

        # Create a root block containing the block with the x-shard tx
        state0.addCrossShardTxListByMinorBlockHash(
            h=b1.header.getHash(),
            txList=CrossShardTransactionList(txList=[]))
        rB = state0.rootTip.createBlockToAppend() \
            .addMinorBlockHeader(b0.header) \
            .addMinorBlockHeader(b1.header) \
            .finalize()
        rB1 = state0.rootTip.createBlockToAppend() \
            .addMinorBlockHeader(b2.header) \
            .addMinorBlockHeader(b1.header) \
            .finalize()

        state0.addRootBlock(rB)

        b00 = b0.createBlockToAppend()
        state0.finalizeAndAddBlock(b00)
        self.assertEqual(state0.headerTip, b00.header)

        # Create another fork that is much longer (however not confirmed by rB)
        b3 = b2.createBlockToAppend()
        state0.finalizeAndAddBlock(b3)
        b4 = b3.createBlockToAppend()
        state0.finalizeAndAddBlock(b4)
        b5 = b1.createBlockToAppend()
        state0.addCrossShardTxListByMinorBlockHash(
            h=b5.header.getHash(),
            txList=CrossShardTransactionList(txList=[]))
        rB2 = rB1.createBlockToAppend() \
            .addMinorBlockHeader(b3.header) \
            .addMinorBlockHeader(b4.header) \
            .addMinorBlockHeader(b5.header) \
            .finalize()

        self.assertFalse(state0.addRootBlock(rB1))
        self.assertTrue(state0.addRootBlock(rB2))
        self.assertEqual(state0.headerTip, b4.header)
        self.assertEqual(state0.metaTip, b4.meta)
        self.assertEqual(state0.rootTip, rB2.header)

    def testShardStateForkResolveWithHigherRootChain(self):
        id1 = Identity.createRandomIdentity()
        acc1 = Address.createFromIdentity(id1, fullShardId=0)

        env = get_test_env(
            genesisAccount=acc1,
            genesisMinorQuarkash=10000000)
        state = create_default_shard_state(env=env, shardId=0)

        b0 = state.getTip().createBlockToAppend()
        state.finalizeAndAddBlock(b0)
        rB = state.rootTip.createBlockToAppend() \
            .addMinorBlockHeader(b0.header) \
            .finalize()

        self.assertEqual(state.headerTip, b0.header)
        self.assertTrue(state.addRootBlock(rB))

        b1 = state.getTip().createBlockToAppend()
        b2 = state.getTip().createBlockToAppend(nonce=1)
        b2.meta.hashPrevRootBlock = rB.header.getHash()
        b3 = state.getTip().createBlockToAppend(nonce=2)
        b3.meta.hashPrevRootBlock = rB.header.getHash()

        state.finalizeAndAddBlock(b1)
        self.assertEqual(state.headerTip, b1.header)

        # Fork happens, although they have the same height, b2 survives since it confirms root block
        state.finalizeAndAddBlock(b2)
        self.assertEqual(state.headerTip, b2.header)

        # b3 confirms the same root block as b2, so it will not override b2
        state.finalizeAndAddBlock(b3)
        self.assertEqual(state.headerTip, b2.header)