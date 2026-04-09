"""Integration tests — full pipeline from AbcBuilder through analysis."""

import tempfile
import pytest

from flashkit.abc.builder import AbcBuilder
from flashkit.abc.parser import parse_abc
from flashkit.abc.writer import serialize_abc
from flashkit.abc.disasm import decode_instructions
from flashkit.abc.constants import TRAIT_Method, TRAIT_Getter, INSTANCE_Interface
from flashkit.swf.builder import SwfBuilder
from flashkit.swf.parser import parse_swf
from flashkit.info.class_info import build_all_classes
from flashkit.workspace import Workspace
from flashkit.search import SearchEngine
from flashkit.analysis.inheritance import InheritanceGraph
from flashkit.analysis.call_graph import CallGraph
from flashkit.analysis.strings import StringIndex


def _build_game_swf():
    """Build a multi-class SWF simulating a small game structure."""
    b = AbcBuilder()
    pub = b.package_namespace("")
    priv = b.private_namespace()
    game_ns = b.package_namespace("com.game")
    ui_ns = b.package_namespace("com.ui")

    obj_mn = b.qname(pub, "Object")
    int_mn = b.qname(pub, "int")
    str_mn = b.qname(pub, "String")
    void_mn = b.qname(pub, "void")

    # IDrawable interface
    idrawable_mn = b.qname(pub, "IDrawable")
    draw_method = b.method()
    b.method_body(draw_method, code=b.asm(b.op_returnvoid()),
                  max_stack=0, local_count=1)
    b.define_class(
        name=idrawable_mn, super_name=obj_mn,
        flags=INSTANCE_Interface,
        instance_traits=[
            b.trait_method(b.qname(priv, "draw"), draw_method),
        ],
    )

    # Entity base class
    entity_mn = b.qname(game_ns, "Entity")
    hp_mn = b.qname(priv, "hp")
    name_field_mn = b.qname(priv, "name")

    get_name = b.method(return_type=str_mn)
    b.method_body(get_name, code=b.asm(
        b.op_getlocal_0(), b.op_pushscope(),
        b.op_pushstring(b.string("entity")),
        b.op_returnvalue(),
    ), max_stack=2, local_count=1)

    update_method = b.method()
    b.method_body(update_method, code=b.asm(
        b.op_getlocal_0(), b.op_pushscope(),
        b.op_pushstring(b.string("updating entity")),
        b.op_pop(),
        b.op_returnvoid(),
    ), max_stack=2, local_count=1)

    b.define_class(
        name=entity_mn, super_name=obj_mn,
        instance_traits=[
            b.trait_slot(hp_mn, type_mn=int_mn, slot_id=1),
            b.trait_slot(name_field_mn, type_mn=str_mn, slot_id=2),
            b.trait_method(b.qname(priv, "getName"), get_name, kind=TRAIT_Getter),
            b.trait_method(b.qname(priv, "update"), update_method),
        ],
        interfaces=[idrawable_mn],
    )

    # Player extends Entity
    player_mn = b.qname(game_ns, "Player")
    score_mn = b.qname(priv, "score")

    attack_method = b.method(params=[int_mn], return_type=void_mn)
    b.method_body(attack_method, code=b.asm(
        b.op_getlocal_0(), b.op_pushscope(),
        b.op_pushstring(b.string("attacking!")),
        b.op_pop(),
        b.op_findpropstrict(b.qname(pub, "trace")),
        b.op_pushstring(b.string("player attacks")),
        b.op_callpropvoid(b.qname(pub, "trace"), 1),
        b.op_returnvoid(),
    ), max_stack=3, local_count=2)

    b.define_class(
        name=player_mn, super_name=entity_mn,
        instance_traits=[
            b.trait_slot(score_mn, type_mn=int_mn, slot_id=3),
            b.trait_method(b.qname(priv, "attack"), attack_method),
        ],
    )

    # Enemy extends Entity
    enemy_mn = b.qname(game_ns, "Enemy")
    b.define_class(name=enemy_mn, super_name=entity_mn)

    # HUD class (UI)
    hud_mn = b.qname(ui_ns, "HUD")
    render_method = b.method()
    b.method_body(render_method, code=b.asm(
        b.op_getlocal_0(), b.op_pushscope(),
        b.op_pushstring(b.string("Score: 0")),
        b.op_pop(),
        b.op_pushstring(b.string("http://assets.example.com/hud.png")),
        b.op_pop(),
        b.op_findpropstrict(entity_mn),
        b.op_constructprop(entity_mn, 0),
        b.op_pop(),
        b.op_returnvoid(),
    ), max_stack=2, local_count=1)
    b.define_class(
        name=hud_mn, super_name=obj_mn,
        instance_traits=[
            b.trait_method(b.qname(priv, "render"), render_method),
        ],
    )

    b.script()
    abc_bytes = serialize_abc(b.build())

    swf = SwfBuilder(version=40, width=800, height=600, fps=30)
    swf.add_abc("GameCode", abc_bytes)
    swf.set_document_class("com.game.Player")
    return swf.build(compress=False)


class TestFullPipeline:
    """End-to-end: AbcBuilder → serialize → SWF → parse → Workspace → analysis."""

    @pytest.fixture
    def game_workspace(self, tmp_path):
        data = _build_game_swf()
        path = tmp_path / "game.swf"
        path.write_bytes(data)
        ws = Workspace()
        ws.load_swf(path)
        return ws

    def test_class_count(self, game_workspace):
        assert game_workspace.class_count == 5

    def test_class_names(self, game_workspace):
        names = {c.name for c in game_workspace.classes}
        assert names == {"IDrawable", "Entity", "Player", "Enemy", "HUD"}

    def test_packages(self, game_workspace):
        packages = {c.package for c in game_workspace.classes}
        assert "com.game" in packages
        assert "com.ui" in packages

    def test_inheritance_graph(self, game_workspace):
        graph = InheritanceGraph.from_classes(game_workspace.classes)

        # Player extends Entity
        parent = graph.get_parent("com.game.Player")
        assert parent == "com.game.Entity"

        # Entity's children
        children = graph.get_children("com.game.Entity")
        child_names = set(children)
        assert "com.game.Player" in child_names
        assert "com.game.Enemy" in child_names

        # Transitive: Player and Enemy are descendants of Entity
        all_children = graph.get_all_children("com.game.Entity")
        assert "com.game.Player" in all_children
        assert "com.game.Enemy" in all_children

    def test_interface_implementors(self, game_workspace):
        graph = InheritanceGraph.from_classes(game_workspace.classes)
        impls = graph.get_implementors("IDrawable")
        assert "com.game.Entity" in impls

    def test_field_resolution(self, game_workspace):
        entity = game_workspace.get_class("Entity")
        assert entity is not None
        hp = entity.get_field("hp")
        assert hp is not None
        assert hp.type_name == "int"

        player = game_workspace.get_class("Player")
        assert player is not None
        score = player.get_field("score")
        assert score is not None
        assert score.type_name == "int"

    def test_method_resolution(self, game_workspace):
        player = game_workspace.get_class("Player")
        assert player is not None
        attack = player.get_method("attack")
        assert attack is not None
        assert attack.return_type == "void"
        assert attack.param_types == ["int"]

    def test_getter_resolution(self, game_workspace):
        entity = game_workspace.get_class("Entity")
        assert entity is not None
        getters = [m for m in entity.methods if m.is_getter]
        assert len(getters) >= 1
        assert any(g.name == "getName" for g in getters)

    def test_string_index(self, game_workspace):
        idx = StringIndex.from_workspace(game_workspace)
        assert idx.unique_string_count > 0

        # Check specific strings pushed in methods
        results = idx.search("attacking")
        assert "attacking!" in results

        urls = idx.url_strings()
        assert any("http://assets.example.com" in u for u in urls)

        ui = idx.ui_strings()
        assert "Score: 0" in ui

    def test_call_graph(self, game_workspace):
        graph = CallGraph.from_workspace(game_workspace)
        assert graph.edge_count > 0

        # HUD.render calls trace (from Player.attack bytecode)
        trace_callers = graph.get_callers("trace")
        assert len(trace_callers) >= 1

    def test_search_engine(self, game_workspace):
        engine = SearchEngine(game_workspace)

        # Find by class name
        results = engine.find_classes(name="Player")
        assert len(results) >= 1

        # Find subclasses of Entity
        subs = engine.find_subclasses("com.game.Entity")
        sub_names = {r.name for r in subs}
        assert "com.game.Player" in sub_names
        assert "com.game.Enemy" in sub_names

        # Find fields of type int
        fields = engine.find_fields(type_name="int")
        assert len(fields) >= 2  # hp, score at minimum

        # Find methods by name
        methods = engine.find_methods(name="attack")
        assert len(methods) >= 1

        # Find string usage
        strings = engine.find_by_string("Score")
        assert len(strings) >= 1

    def test_disasm(self, game_workspace):
        """Method bodies should be decodable."""
        for abc in game_workspace.abc_blocks:
            for body in abc.method_bodies:
                instructions = decode_instructions(body.code)
                assert len(instructions) > 0
                # All instructions should have valid offsets
                for instr in instructions:
                    assert instr.offset >= 0
                    assert instr.size >= 1


class TestSwfRoundTrip:
    """SWF build → parse → rebuild → reparse preserves everything."""

    def test_full_swf_roundtrip(self):
        data = _build_game_swf()

        # Parse
        header, tags, version, length = parse_swf(data)
        assert version == 40

        # Extract ABC and verify classes
        from flashkit.swf.tags import TAG_DO_ABC2
        abc_tags = [t for t in tags if t.tag_type == TAG_DO_ABC2]
        assert len(abc_tags) == 1
        assert abc_tags[0].name == "GameCode"

        # Extract and parse ABC data from the tag
        tag = abc_tags[0]
        null_idx = tag.payload.index(0, 4)
        abc_data = tag.payload[null_idx + 1:]
        abc = parse_abc(abc_data)
        classes = build_all_classes(abc)
        assert len(classes) == 5

    def test_abc_byte_roundtrip(self):
        """AbcBuilder → serialize → parse → serialize = identical bytes."""
        b = AbcBuilder()
        pub = b.package_namespace("")
        priv = b.private_namespace()
        ns = b.package_namespace("com.test")

        cls = b.qname(ns, "RoundTripTest")
        int_mn = b.qname(pub, "int")
        field = b.qname(priv, "value")

        m = b.method(params=[int_mn], return_type=int_mn, param_names=["x"])
        b.method_body(m, code=b.asm(
            b.op_getlocal_0(), b.op_pushscope(),
            b.op_getlocal_1(),
            b.op_returnvalue(),
        ), max_stack=2, local_count=2)

        b.define_class(
            name=cls, super_name=0,
            instance_traits=[
                b.trait_slot(field, type_mn=int_mn, slot_id=1),
                b.trait_method(b.qname(priv, "process"), m),
            ])
        b.script()

        abc = b.build()
        raw1 = serialize_abc(abc)
        abc2 = parse_abc(raw1)
        raw2 = serialize_abc(abc2)
        assert raw1 == raw2
